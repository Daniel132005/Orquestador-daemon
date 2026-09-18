import json
import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, IntegrityError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from . import challenges, docker_client
from .models import Instance, SolvedChallenge


@login_required
def terminal_page(request):
    """Página con la consola Xterm.js (ver SDD 4.5)."""
    return render(request, "ctf/terminal.html")


def _challenge_summary(reto: dict) -> dict:
    """Campos de un reto que expone la API: catálogo e instancia activa
    comparten esta forma, para que el frontend no tenga que distinguir."""
    return {
        "slug": reto["slug"],
        "name": reto["name"],
        "owasp": reto["owasp"],
        "difficulty": reto["difficulty"],
        "xp": reto.get("xp", 100),
        "description": reto["description"],
        "objective": reto["objective"],
        "first_step": reto["first_step"],
        "expected_result": reto["expected_result"],
    }


@login_required
@require_GET
def challenge_list(request):
    """Catálogo de retos que el frontend ofrece para elegir antes de desplegar."""
    solved_slugs = set(
        SolvedChallenge.objects.filter(user=request.user).values_list("challenge_slug", flat=True)
    )
    user_xp = sum(
        SolvedChallenge.objects.filter(user=request.user).values_list("xp_awarded", flat=True)
    )
    return JsonResponse(
        {
            "challenges": [
                {
                    **_challenge_summary(c),
                    "solved": c["slug"] in solved_slugs,
                }
                for c in challenges.list_challenges()
            ],
            "default": challenges.DEFAULT_CHALLENGE,
            "user_xp": user_xp,
        }
    )


@login_required
@require_GET
def instance_status(request):
    """
    Estado de la instancia del usuario más los límites configurados, para
    que el frontend sepa qué mostrar al cargar la página (y no ofrezca
    "iniciar" cuando ya hay una instancia viva).
    """
    instance = Instance.objects.filter(user=request.user).first()
    reto = challenges.get_challenge(instance.challenge) if instance else None
    solved_slugs = set(
        SolvedChallenge.objects.filter(user=request.user).values_list("challenge_slug", flat=True)
    )
    user_xp = sum(
        SolvedChallenge.objects.filter(user=request.user).values_list("xp_awarded", flat=True)
    )
    payload = {
        "active": instance is not None,
        "container_id": instance.container_id if instance else None,
        "network_name": instance.network_name if instance else None,
        "created_at": instance.created_at.isoformat() if instance else None,
        "challenge": (
            {
                **_challenge_summary({**reto, "slug": instance.challenge}),
                "solved": instance.challenge in solved_slugs,
            }
            if instance and reto
            else ({"slug": instance.challenge, "name": instance.challenge, "solved": False} if instance else None)
        ),
        "user_xp": user_xp,
        "challenge_solved": (instance.challenge in solved_slugs) if instance else False,
        "limits": {
            "memory_mb": settings.CTF_MEMORY_LIMIT_BYTES // (1024 * 1024),
            "cpus": settings.CTF_NANO_CPUS / 1_000_000_000,
            "pids": settings.CTF_PIDS_LIMIT,
        },
        "inactivity_timeout_seconds": settings.INSTANCE_INACTIVITY_TIMEOUT_SECONDS,
        "max_lifetime_seconds": settings.INSTANCE_MAX_LIFETIME_SECONDS,
    }
    return JsonResponse(payload)


@login_required
@require_POST
def submit_flag(request):
    """
    POST /api/challenges/submit/
    Body: {"flag": "...", "slug": "..."} (si no viene slug, usa la de la instancia activa).
    """
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    submitted_flag = data.get("flag", "").strip()
    slug = data.get("slug", "").strip()

    if not submitted_flag:
        return JsonResponse({"error": "La bandera no puede estar vacía"}, status=400)

    if not slug:
        instance = Instance.objects.filter(user=request.user).first()
        if instance:
            slug = instance.challenge

    if not slug:
        return JsonResponse({"error": "No se especificó qué reto se está resolviendo"}, status=400)

    reto = challenges.get_challenge(slug)
    if not reto:
        return JsonResponse({"error": f"Reto '{slug}' no encontrado"}, status=404)

    is_valid, xp_to_award = challenges.validate_flag(slug, submitted_flag)
    if not is_valid:
        return JsonResponse(
            {
                "success": False,
                "error": "Bandera incorrecta. ¡Seguí investigando!",
            },
            status=400,
        )

    already_solved = SolvedChallenge.objects.filter(user=request.user, challenge_slug=slug).exists()
    if not already_solved:
        SolvedChallenge.objects.create(
            user=request.user,
            challenge_slug=slug,
            xp_awarded=xp_to_award,
        )
        xp_awarded = xp_to_award
        newly_solved = True
    else:
        xp_awarded = 0
        newly_solved = False

    total_xp = sum(
        SolvedChallenge.objects.filter(user=request.user).values_list("xp_awarded", flat=True)
    )

    return JsonResponse(
        {
            "success": True,
            "newly_solved": newly_solved,
            "xp_awarded": xp_awarded,
            "total_xp": total_xp,
            "challenge_name": reto["name"],
            "challenge_slug": slug,
            "message": (
                f"¡Vulnerabilidad encontrada! Has resuelto {reto['name']}. Sumaste +{xp_awarded} XP."
                if newly_solved
                else f"¡Bandera correcta! Ya habías completado este reto previamente."
            ),
        }
    )


@login_required
@require_POST
def start_instance(request):
    """
    POST /api/instance/start/ — ver flujo en SDD 5.1.

    Quién gana la carrera entre dos peticiones simultáneas del mismo
    usuario lo decide la restricción `OneToOneField` del modelo: el
    perdedor recibe `IntegrityError` al insertar y limpia lo que había
    creado en Docker.

    Las llamadas a Docker quedan deliberadamente FUERA de cualquier
    transacción. Envolverlas duraba casi un segundo con la base tomada, y
    como SQLite admite un solo escritor, varias peticiones simultáneas
    morían con `database is locked` — un error que no es `IntegrityError`,
    así que ni siquiera se limpiaban los contenedores ya creados.
    """
    if Instance.objects.filter(user=request.user).exists():
        return JsonResponse({"error": "Ya tienes una instancia activa"}, status=409)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Cuerpo de la petición inválido"}, status=400)

    challenge_slug = body.get("challenge") or challenges.DEFAULT_CHALLENGE
    reto = challenges.get_challenge(challenge_slug)
    if reto is None:
        return JsonResponse({"error": f"Reto desconocido: {challenge_slug}"}, status=400)

    network_name = f"ctf-net-{request.user.pk}-{uuid.uuid4().hex[:8]}"
    network_id = docker_client.create_network(network_name)

    container_id = None
    try:
        container_id = docker_client.create_container(
            image=reto["image"],
            network_name=network_name,
            mem_limit_bytes=settings.CTF_MEMORY_LIMIT_BYTES,
            nano_cpus=settings.CTF_NANO_CPUS,
            pids_limit=settings.CTF_PIDS_LIMIT,
        )
        docker_client.start_container(container_id)
    except docker_client.DockerClientError as exc:
        # Si el contenedor alcanzó a crearse hay que borrarlo antes que la
        # red: quedaría sin fila en la base, y el watchdog solo mira filas,
        # así que nadie lo reclamaría nunca. Ocurre, por ejemplo, cuando
        # `create` funciona y `start` falla.
        if container_id is not None:
            docker_client.remove_container(container_id)
        docker_client.remove_network(network_id)
        return JsonResponse({"error": str(exc)}, status=502)

    try:
        instance = Instance.objects.create(
            user=request.user,
            challenge=challenge_slug,
            container_id=container_id,
            network_id=network_id,
            network_name=network_name,
        )
    except IntegrityError:
        # Otra petición del mismo usuario llegó primero.
        docker_client.destroy_instance(container_id, network_id)
        return JsonResponse({"error": "Ya tienes una instancia activa"}, status=409)
    except DatabaseError as exc:
        # Cualquier otro fallo de base de datos: sin fila que lo respalde,
        # el contenedor sería un huérfano que nadie volvería a reclamar.
        docker_client.destroy_instance(container_id, network_id)
        return JsonResponse({"error": f"Error de base de datos: {exc}"}, status=503)

    return JsonResponse(
        {
            "container_id": instance.container_id,
            "created_at": instance.created_at.isoformat(),
        },
        status=201,
    )


@login_required
@require_POST
def stop_instance(request):
    """POST /api/instance/stop/ — destruye contenedor y red del usuario."""
    try:
        instance = Instance.objects.get(user=request.user)
    except Instance.DoesNotExist:
        return JsonResponse({"error": "No tienes ninguna instancia activa"}, status=404)

    try:
        docker_client.destroy_instance(instance.container_id, instance.network_id)
    except docker_client.DockerClientError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    instance.delete()
    return JsonResponse({"status": "detenida"})
