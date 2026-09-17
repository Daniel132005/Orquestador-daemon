import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, IntegrityError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from . import docker_client
from .models import Instance


@login_required
def terminal_page(request):
    """Página con la consola Xterm.js (ver SDD 4.5)."""
    return render(request, "ctf/terminal.html")


@login_required
@require_GET
def instance_status(request):
    """
    Estado de la instancia del usuario más los límites configurados, para
    que el frontend sepa qué mostrar al cargar la página (y no ofrezca
    "iniciar" cuando ya hay una instancia viva).
    """
    instance = Instance.objects.filter(user=request.user).first()
    payload = {
        "active": instance is not None,
        "container_id": instance.container_id if instance else None,
        "network_name": instance.network_name if instance else None,
        "created_at": instance.created_at.isoformat() if instance else None,
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

    network_name = f"ctf-net-{request.user.pk}-{uuid.uuid4().hex[:8]}"
    network_id = docker_client.create_network(network_name)

    container_id = None
    try:
        container_id = docker_client.create_container(
            image=settings.CTF_CHALLENGE_IMAGE,
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
