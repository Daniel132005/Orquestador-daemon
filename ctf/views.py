import json
import re
import unicodedata
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, IntegrityError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from . import challenges, docker_client
from .models import Instance, PlatformSettings, SolvedChallenge

# Intentos de bandera erronea permitidos por instancia antes de destruirla.
MAX_INTENTOS_BANDERA = 5

# Patron de nombre de usuario: 3-20 caracteres, solo letras (con acentos/ñ)
# y guion bajo. Mismo criterio en crear y editar.
PATRON_USUARIO = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ_]{3,20}")

# Filtro basico de groserias (es-Latam) para el nombre de usuario. NO es
# exhaustivo ni infalible: corta lo evidente en crear/editar. Se comparan
# ya normalizadas (minusculas, sin acentos) contra el nombre normalizado.
# Se evitan a proposito palabras que son subcadena de nombres/terminos
# inocentes (ej. "culo" en "articulo") para no bloquear cuentas legitimas.
PALABRAS_OBSCENAS = {
    # Generales / latam
    "puta", "puto", "putita", "putito", "puton", "mierda", "verga",
    "verguero", "vergacion", "pija", "pendejo", "pendeja", "cabron",
    "cabrona", "culero", "chinga", "chingada", "maricon", "maricona",
    "gilipollas", "capullo", "zorra", "pelotudo", "boludo", "conchudo",
    "malparido", "hijueputa", "hdp", "ctm", "conchetumare", "joto",
    "carajo", "pinche", "gonorrea", "malnacido", "concha",
    # Venezolanas (jerga vulgar). Se evitan formas cortas que sean
    # subcadena de palabras inocentes: por eso NO va "cono" (coño) suelto,
    # porque rompe "conocer"; van las formas compuestas inequivocas.
    "marico", "marica", "guevon", "webon", "huevon", "huebon", "guebon",
    "mamaguevo", "mamahuevo", "mamaguebo", "mamahuebo", "pajuo", "pajua",
    "pajudo", "puneta", "conazo", "conoetumadre", "conodetumadre",
    "singao", "singar", "singada", "cojeculo", "carechimba", "culicagao",
    "culicagado", "cagon", "cagada", "bicho", "bomba",
}


def _normalizar(texto: str) -> str:
    """Minusculas y sin acentos, para comparar de forma robusta."""
    descompuesto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def contiene_palabra_obscena(nombre: str) -> bool:
    limpio = _normalizar(nombre)
    return any(mala in limpio for mala in PALABRAS_OBSCENAS)


@login_required
def terminal_page(request):
    """Página con la consola Xterm.js (ver SDD 4.5)."""
    return render(request, "ctf/terminal.html")


@login_required
def platform_settings_view(request):
    """
    GET/POST /api/platform-settings/ — panel escondido (5 clicks en el
    nombre de usuario, ver terminal.js) para ajustar el umbral de
    inactividad y la vida máxima sin pasar por /admin/.

    Que esté escondido en el frontend es solo para que no cualquiera se
    tropiece con él por accidente -- el control real de acceso es este
    chequeo de `is_staff`, van a devolver 403 igual si alguien le pega
    directo a la URL sin ser staff.
    """
    if not request.user.is_staff:
        return JsonResponse({"error": "No tienes permiso para ver esto"}, status=403)

    campos = (
        "inactivity_timeout_seconds",
        "time_limit_basico_seconds",
        "time_limit_intermedio_seconds",
        "time_limit_dificil_seconds",
        "max_lifetime_seconds",
    )

    if request.method == "GET":
        config = PlatformSettings.actual()
        return JsonResponse({campo: getattr(config, campo) for campo in campos})

    if request.method == "POST":
        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        try:
            valores = {campo: int(data[campo]) for campo in campos}
        except (KeyError, TypeError, ValueError):
            return JsonResponse({"error": "Faltan campos o no son números"}, status=400)

        if any(valor < 30 for valor in valores.values()):
            return JsonResponse(
                {"error": "Los valores tienen que ser de al menos 30 segundos"}, status=400
            )

        config = PlatformSettings.actual()
        for campo, valor in valores.items():
            setattr(config, campo, valor)
        config.save()
        return JsonResponse({campo: getattr(config, campo) for campo in campos})

    return JsonResponse({"error": "Método no permitido"}, status=405)


@login_required
@require_GET
def live_instances_view(request):
    """
    GET /api/platform-settings/instances/ — panel oculto: cruza lo que
    dice Docker de verdad (`docker_client.list_ctf_containers`) contra
    las filas de `Instance`, para ver de un vistazo:

    - huérfanos: contenedor real sin fila que lo reclame.
    - fantasmas: fila en la base sin contenedor real detrás.
    - el resto, en sincronía entre las dos fuentes.

    Mismo control de acceso que `platform_settings_view`: solo staff.
    """
    if not request.user.is_staff:
        return JsonResponse({"error": "No tienes permiso para ver esto"}, status=403)

    try:
        contenedores = docker_client.list_ctf_containers()
    except docker_client.DockerClientError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    instancias = list(Instance.objects.select_related("user").all())
    por_container_id = {i.container_id: i for i in instancias}
    vistos = set()

    User = get_user_model()

    def usuario_por_red(network_name: str | None) -> str | None:
        """
        Para un huérfano (sin fila en `Instance`) no hay otra forma de
        saber de quién era: se le adivina el usuario al nombre de la
        red, que la plataforma siempre arma como
        `ctf-net-{id_usuario}-{random}` (ver `start_instance`).
        """
        if not network_name or not network_name.startswith("ctf-net-"):
            return None
        try:
            user_pk = int(network_name.split("-")[2])
        except (IndexError, ValueError):
            return None
        usuario = User.objects.filter(pk=user_pk).first()
        return usuario.username if usuario else f"(usuario #{user_pk}, no existe más)"

    filas = []
    for c in contenedores:
        instancia = por_container_id.get(c["container_id"])
        vistos.add(c["container_id"])

        if instancia:
            usuario = instancia.user.username
        else:
            deducido = usuario_por_red(c["network_name"])
            usuario = f"{deducido} (deducido, sin fila)" if deducido else None

        filas.append(
            {
                "container_id": c["container_id"],
                "network_id": c["network_id"],
                "network_name": c["network_name"],
                "image": c["image"],
                "docker_status": c["status"],
                "created": c["created"],
                "estado": "activa" if instancia else "huerfana",
                "user": usuario,
                "challenge": instancia.challenge if instancia else None,
                "last_activity": instancia.last_activity.isoformat() if instancia else None,
            }
        )

    for instancia in instancias:
        if instancia.container_id not in vistos:
            filas.append(
                {
                    "container_id": instancia.container_id,
                    "network_id": instancia.network_id,
                    "image": None,
                    "docker_status": None,
                    "created": None,
                    "estado": "fantasma",
                    "user": instancia.user.username,
                    "challenge": instancia.challenge,
                    "last_activity": instancia.last_activity.isoformat(),
                }
            )

    return JsonResponse({"instances": filas})


@login_required
@require_POST
def destroy_container_view(request):
    """
    POST /api/platform-settings/instances/destroy/ — destruye cualquier
    contenedor+red desde el panel oculto, tenga fila en `Instance` o no.
    Es la forma de limpiar un huérfano de verdad sin usar `docker` a
    mano (que fue justo lo que causó el incidente del Día 15).
    """
    if not request.user.is_staff:
        return JsonResponse({"error": "No tienes permiso para hacer esto"}, status=403)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    container_id = (data.get("container_id") or "").strip()
    if not container_id:
        return JsonResponse({"error": "Falta container_id"}, status=400)

    instance = Instance.objects.filter(container_id=container_id).first()
    network_id = data.get("network_id") or (instance.network_id if instance else None)

    try:
        docker_client.stop_container(container_id)
        docker_client.remove_container(container_id)
        if network_id:
            docker_client.remove_network(network_id)
    except docker_client.DockerClientError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    if instance:
        instance.delete()

    return JsonResponse({"status": "destruido"})


@login_required
def manage_users_view(request):
    """
    GET/POST /api/platform-settings/users/ — panel oculto: crear cuentas
    (profesor, estudiantes) sin pasar por `/admin/` ni por
    `manage.py createsuperuser` a mano. Mismo control de acceso que el
    resto del panel: `is_staff`.
    """
    if not request.user.is_staff:
        return JsonResponse({"error": "No tienes permiso para hacer esto"}, status=403)

    User = get_user_model()

    if request.method == "GET":
        usuarios = [
            {
                "id": u.id,
                "username": u.username,
                "is_staff": u.is_staff,
                "is_self": u.id == request.user.id,
                "date_joined": u.date_joined.isoformat(),
            }
            for u in User.objects.order_by("username")
        ]
        return JsonResponse({"users": usuarios})

    if request.method == "POST":
        try:
            data = json.loads(request.body) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON inválido"}, status=400)

        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        es_staff = bool(data.get("is_staff"))

        if not username or not password:
            return JsonResponse({"error": "Usuario y clave son obligatorios"}, status=400)
        error_nombre = _error_username(username, User)
        if error_nombre:
            return JsonResponse({"error": error_nombre}, status=400)
        if len(password) < 6:
            return JsonResponse(
                {"error": "La clave tiene que tener al menos 6 caracteres"}, status=400
            )

        user = User.objects.create_user(username=username, password=password)
        if es_staff:
            user.is_staff = True
            user.save()

        return JsonResponse(
            {"status": "creado", "id": user.id, "username": user.username, "is_staff": user.is_staff}
        )

    return JsonResponse({"error": "Método no permitido"}, status=405)


def _error_username(username: str, User, excluir_pk=None) -> str | None:
    """
    Valida el nombre de usuario para crear/editar. Devuelve el mensaje de
    error, o None si es válido. `excluir_pk` deja pasar el propio nombre al
    editar (no choca consigo mismo).
    """
    if not PATRON_USUARIO.fullmatch(username):
        return (
            "El usuario tiene que tener entre 3 y 20 caracteres, solo "
            "letras y guion bajo (sin números ni espacios)."
        )
    if contiene_palabra_obscena(username):
        return "Ese nombre de usuario no está permitido."
    existe = User.objects.filter(username=username)
    if excluir_pk is not None:
        existe = existe.exclude(pk=excluir_pk)
    if existe.exists():
        return f"Ya existe un usuario '{username}'"
    return None


@login_required
@require_POST
def manage_user_detail_view(request, user_id):
    """
    POST /api/platform-settings/users/<id>/ — editar o eliminar una cuenta
    desde el panel oculto. Solo staff. Se usa POST + campo `accion` en el
    cuerpo (en vez de PATCH/DELETE) para no depender de métodos que algún
    proxy/túnel podría filtrar.

    Acciones:
      - "eliminar": borra la cuenta.
      - "editar": cambia nombre, rol (is_staff) y opcionalmente la clave.

    Salvaguarda contra quedarse sin acceso: no podés eliminar ni quitarte
    el rol staff a tu propia cuenta.
    """
    if not request.user.is_staff:
        return JsonResponse({"error": "No tienes permiso para hacer esto"}, status=403)

    User = get_user_model()
    objetivo = User.objects.filter(pk=user_id).first()
    if objetivo is None:
        return JsonResponse({"error": "Ese usuario no existe"}, status=404)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido"}, status=400)

    accion = (data.get("accion") or "").strip()
    es_uno_mismo = objetivo.id == request.user.id

    if accion == "eliminar":
        if es_uno_mismo:
            return JsonResponse(
                {"error": "No podés eliminar tu propia cuenta."}, status=400
            )
        nombre = objetivo.username
        objetivo.delete()
        return JsonResponse({"status": "eliminado", "username": nombre})

    if accion == "editar":
        nuevo_nombre = (data.get("username") or "").strip()
        nueva_clave = data.get("password") or ""
        nuevo_rol = data.get("is_staff")

        if nuevo_nombre and nuevo_nombre != objetivo.username:
            error_nombre = _error_username(nuevo_nombre, User, excluir_pk=objetivo.pk)
            if error_nombre:
                return JsonResponse({"error": error_nombre}, status=400)
            objetivo.username = nuevo_nombre

        if nueva_clave:
            if len(nueva_clave) < 6:
                return JsonResponse(
                    {"error": "La clave tiene que tener al menos 6 caracteres"},
                    status=400,
                )
            objetivo.set_password(nueva_clave)

        if nuevo_rol is not None:
            quiere_staff = bool(nuevo_rol)
            # No podés quitarte a vos mismo el rol staff: te dejaría sin
            # acceso al panel en el acto.
            if es_uno_mismo and not quiere_staff:
                return JsonResponse(
                    {"error": "No podés quitarte a vos mismo el rol de staff."},
                    status=400,
                )
            objetivo.is_staff = quiere_staff

        objetivo.save()
        return JsonResponse(
            {
                "status": "editado",
                "id": objetivo.id,
                "username": objetivo.username,
                "is_staff": objetivo.is_staff,
            }
        )

    return JsonResponse({"error": "Acción no reconocida"}, status=400)


def _challenge_summary(reto: dict) -> dict:
    """Campos de un reto que expone la API: catálogo e instancia activa
    comparten esta forma, para que el frontend no tenga que distinguir."""
    return {
        "slug": reto["slug"],
        "name": reto["name"],
        "owasp": reto["owasp"],
        "difficulty": reto["difficulty"],
        "xp": reto.get("xp", 100),
        "time_limit_seconds": reto.get("time_limit_seconds", challenges.time_limit_for(reto["slug"])),
        "image": reto["image"],
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
    config = PlatformSettings.actual()
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
        "inactivity_timeout_seconds": config.inactivity_timeout_seconds,
        "max_lifetime_seconds": (
            challenges.time_limit_for(instance.challenge) if instance else config.max_lifetime_seconds
        ),
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
        instance = Instance.objects.filter(user=request.user).first()
        # El limite aplica sobre la instancia activa del MISMO reto (resuelto
        # o no: la idea es cortar el spam/fuerza bruta de banderas). Contar y
        # destruir sobre la instancia hace que el contador se resetee al
        # redesplegar (fila nueva, contador en 0).
        if instance and instance.challenge == slug:
            instance.failed_flag_attempts += 1
            instance.save(update_fields=["failed_flag_attempts"])
            if instance.failed_flag_attempts >= MAX_INTENTOS_BANDERA:
                try:
                    docker_client.destroy_instance(
                        instance.container_id, instance.network_id
                    )
                except docker_client.DockerClientError:
                    # Si Docker falla, se borra la fila igual; el watchdog
                    # limpia cualquier resto en su proximo barrido.
                    pass
                instance.delete()
                return JsonResponse(
                    {
                        "success": False,
                        "instance_destroyed": True,
                        "error": (
                            f"{MAX_INTENTOS_BANDERA} intentos fallidos: la "
                            "instancia fue destruida. Despliega una nueva "
                            "para reintentar."
                        ),
                    },
                    status=400,
                )
            restantes = MAX_INTENTOS_BANDERA - instance.failed_flag_attempts
            return JsonResponse(
                {
                    "success": False,
                    "attempts_left": restantes,
                    "error": (
                        f"Bandera incorrecta. Te queda{'n' if restantes != 1 else ''} "
                        f"{restantes} intento{'s' if restantes != 1 else ''} "
                        "antes de que se destruya la instancia."
                    ),
                },
                status=400,
            )
        return JsonResponse(
            {
                "success": False,
                "error": "Bandera incorrecta. ¡Sigue investigando!",
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
