"""
Capa de acceso a la Docker Engine API hablando directo con el socket Unix
del daemon (ver SDD 4.1), sin usar `docker-py`.

- Operaciones REST normales (crear/arrancar/detener/borrar contenedores y
  redes, crear un `exec`) van por `requests-unixsocket`.
- El arranque del `exec` (`start_exec_hijacked`) necesita un socket crudo
  bidireccional, así que se abre a mano con la librería estándar `socket`
  y se hace un upgrade manual de la conexión HTTP.
"""

from __future__ import annotations

import asyncio
import io
import json
import socket
import tarfile

import requests_unixsocket
from django.conf import settings

BASE_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"


class DockerClientError(Exception):
    """Cualquier error de comunicación con el daemon de Docker."""


def _docker_socket_path() -> str:
    return getattr(settings, "DOCKER_SOCKET_PATH", "/var/run/docker.sock")


def _session() -> requests_unixsocket.Session:
    return requests_unixsocket.Session()


def _check(response, expected):
    if response.status_code not in expected:
        raise DockerClientError(
            f"Docker API respondió {response.status_code}: {response.text}"
        )
    return response


# --- Redes ---------------------------------------------------------------


def create_network(name: str) -> str:
    """Crea una red bridge interna (sin salida a internet) para un usuario."""
    payload = {
        "Name": name,
        "Driver": "bridge",
        "Internal": True,
        "CheckDuplicate": True,
    }
    response = _check(
        _session().post(f"{BASE_URL}/networks/create", json=payload), (201,)
    )
    return response.json()["Id"]


def remove_network(network_id: str) -> None:
    response = _session().delete(f"{BASE_URL}/networks/{network_id}")
    if response.status_code not in (204, 404):
        raise DockerClientError(
            f"No se pudo borrar la red {network_id}: {response.text}"
        )


# --- Contenedores ----------------------------------------------------------


def create_container(
    image: str,
    network_name: str,
    mem_limit_bytes: int,
    nano_cpus: int,
    pids_limit: int,
) -> str:
    """
    Crea (sin arrancar) un contenedor conectado a `network_name`, con los
    límites de recursos descritos en el SDD 6: memoria, CPU (NanoCpus) y
    número máximo de procesos (PidsLimit), traducidos por Docker a cgroups.
    """
    payload = {
        "Image": image,
        "Tty": True,
        "OpenStdin": True,
        "HostConfig": {
            "NetworkMode": network_name,
            "Memory": mem_limit_bytes,
            "NanoCpus": nano_cpus,
            "PidsLimit": pids_limit,
            "CapDrop": ["ALL"],
            # Los retos usan `sudo` para separar privilegios dentro del
            # contenedor (ver challenges/_base/Dockerfile): la consola
            # corre sin privilegios, y solo el comando exacto de la app
            # vulnerable puede correr como root. Con `CapDrop: ALL` a
            # secas, el kernel le recorta el "bounding set" a CUALQUIER
            # proceso del contenedor, así que ni siquiera un binario
            # setuid-root como `sudo` puede terminar de cambiar de
            # usuario (falla con "unable to change to root gid").
            # Se agregan de vuelta solo las dos que sudo necesita para
            # eso, nada más — sigue sin poder tocar la red (NET_RAW/ADMIN)
            # ni el resto de lo que el Día 3 verificó que no hacía falta.
            "CapAdd": ["SETUID", "SETGID"],
            # No se usa `ReadonlyRootfs: True` para permitir que el orquestador
            # inyecte la bandera dinámica personalizada (`/app/flag.txt`) vía
            # la Docker Engine API antes de arrancar. La seguridad del sistema
            # de archivos se mantiene intacta: `/app` y los binarios pertenecen a
            # `root:root` (0755), por lo que el usuario `retador` no puede escribir
            # en `/app` ni leer `flag.txt` (modo 0600).
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"},
            "AutoRemove": False,
            # `PidsLimit` frena una bomba de PROCESOS, pero un descriptor de
            # archivo es otro recurso del kernel: sin este techo, `nofile`
            # queda en ~1M (el default del daemon), suficiente para que un
            # bucle que abre archivos degrade el contenedor. 1024/2048 es de
            # sobra para cualquier reto y acota ese recurso explícitamente.
            "Ulimits": [{"Name": "nofile", "Soft": 1024, "Hard": 2048}],
            # La salida del estudiante viaja por el `exec` (no por el log del
            # contenedor), así que hoy esto no crece -- pero el stdout del
            # proceso principal SÍ va a un json-file en el disco del host, sin
            # tope por defecto. Capearlo es un seguro barato por si algún reto
            # llegara a correr su app como proceso principal.
            "LogConfig": {
                "Type": "json-file",
                "Config": {"max-size": "10m", "max-file": "3"},
            },
            # El PID 1 de estos contenedores es `/bin/sh` (ver Dockerfile de
            # cada reto), que nunca hace `wait()` sobre hijos huérfanos. Sin
            # esto, una fork bomb deja zombis para siempre pegados contra
            # `PidsLimit` -- PidsLimit sí evita que tumbe el host, pero el
            # cupo de PIDs queda agotado de forma permanente y el estudiante
            # no puede seguir usando su propia consola (verificado: hasta
            # `sudo` deja de poder arrancar el reto). `Init: true` mete un
            # init mínimo (tini) como PID 1 real, que sí cosecha zombis.
            "Init": True,
        },
    }
    response = _check(
        _session().post(f"{BASE_URL}/containers/create", json=payload), (201,)
    )
    return response.json()["Id"]


def inject_challenge_flag(container_id: str, slug: str, flag: str) -> None:
    """
    Inyecta la bandera dinámica del estudiante en el contenedor antes de
    arrancarlo. Se sube vía la Docker Engine API (PUT /containers/{id}/archive)
    con permisos root:root (0600) para que el usuario sin privilegios
    (retador) no pueda leerla directamente sin explotar la falla.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        if slug == "idor":
            # Para IDOR la bandera vive en pedidos.json (pedido 1337)
            pedidos = {
                "1001": {
                    "cliente": "invitado",
                    "producto": "Sticker ROOT_LABS",
                    "nota": "Tu pedido.",
                },
                "1002": {
                    "cliente": "invitado",
                    "producto": "Taza CTF",
                    "nota": "Tu pedido.",
                },
                "1337": {
                    "cliente": "admin",
                    "producto": "Acceso VIP",
                    "flag": flag,
                },
            }
            data = json.dumps(pedidos, indent=2, ensure_ascii=False).encode("utf-8")
            ti = tarfile.TarInfo(name="pedidos.json")
            ti.size = len(data)
            ti.mode = 0o600
            ti.uname = "root"
            ti.gname = "root"
            tar.addfile(ti, io.BytesIO(data))
        else:
            # Para los otros 9 retos, la bandera vive en /app/flag.txt
            data = f"{flag}\n".encode("utf-8")
            ti = tarfile.TarInfo(name="flag.txt")
            ti.size = len(data)
            ti.mode = 0o600
            ti.uname = "root"
            ti.gname = "root"
            tar.addfile(ti, io.BytesIO(data))

    buf.seek(0)
    response = _session().put(
        f"{BASE_URL}/containers/{container_id}/archive",
        params={"path": "/app"},
        data=buf.getvalue(),
        headers={"Content-Type": "application/x-tar"},
    )
    if response.status_code not in (200, 204):
        raise DockerClientError(
            f"No se pudo inyectar la bandera en {container_id[:12]}: {response.text}"
        )


def start_container(container_id: str) -> None:
    _check(
        _session().post(f"{BASE_URL}/containers/{container_id}/start"), (204,)
    )


def stop_container(container_id: str, timeout: int = 5) -> None:
    response = _session().post(
        f"{BASE_URL}/containers/{container_id}/stop", params={"t": timeout}
    )
    if response.status_code not in (204, 304, 404):
        raise DockerClientError(
            f"No se pudo detener el contenedor {container_id}: {response.text}"
        )


def remove_container(container_id: str) -> None:
    response = _session().delete(
        f"{BASE_URL}/containers/{container_id}", params={"force": "true"}
    )
    if response.status_code not in (204, 404):
        raise DockerClientError(
            f"No se pudo borrar el contenedor {container_id}: {response.text}"
        )


def destroy_instance(container_id: str, network_id: str) -> None:
    """Detiene y borra el contenedor, y luego borra su red aislada."""
    stop_container(container_id)
    remove_container(container_id)
    remove_network(network_id)


def list_ctf_containers() -> list[dict]:
    """
    Contenedores reales que corren alguna imagen `ctf-reto-*`, tal cual
    los ve Docker -- no lo que dice la base de datos. Es la única forma
    de detectar un huérfano (contenedor sin fila en `Instance`) o una
    fila fantasma (instancia sin contenedor real): comparando esto
    contra `Instance.objects.all()` en la vista que lo expone
    (ver `views.live_instances_view`, panel oculto).
    """
    response = _check(
        _session().get(f"{BASE_URL}/containers/json", params={"all": "true"}),
        (200,),
    )
    contenedores = []
    for c in response.json():
        if not c.get("Image", "").startswith("ctf-reto-"):
            continue
        redes = c.get("NetworkSettings", {}).get("Networks", {})
        red = next(iter(redes.items()), (None, {}))
        contenedores.append(
            {
                "container_id": c["Id"],
                "name": (c.get("Names") or ["/?"])[0].lstrip("/"),
                "image": c.get("Image"),
                "state": c.get("State"),
                "status": c.get("Status"),
                "created": c.get("Created"),
                "network_name": red[0],
                "network_id": red[1].get("NetworkID"),
            }
        )
    return contenedores


# --- Exec + hijack -----------------------------------------------------


def create_exec(
    container_id: str,
    cmd: list[str] | None = None,
    tty: bool = True,
    attach: bool = True,
) -> str:
    payload = {
        "AttachStdin": attach,
        "AttachStdout": attach,
        "AttachStderr": attach,
        "Tty": tty,
        "Cmd": cmd or ["/bin/sh"],
    }
    response = _check(
        _session().post(f"{BASE_URL}/containers/{container_id}/exec", json=payload),
        (201,),
    )
    return response.json()["Id"]


def console_exec_command(pid_file: str, shell: str | None = None) -> list[str]:
    """
    Comando del shell de una consola. Antes de convertirse en el shell
    interactivo deja su PID en un archivo, para poder matarlo cuando el
    estudiante se desconecte (ver `terminate_console`).

    `exec` reemplaza el proceso conservando el mismo PID, así que el número
    guardado sigue siendo válido.

    El envoltorio siempre es `/bin/sh` porque existe en cualquier imagen.
    Para el shell interactivo se prefiere `bash` cuando la imagen lo trae,
    porque es el que activa `bracketed paste`: sin él, un texto pegado se
    ejecuta solo, línea por línea, sin darle al estudiante ocasión de
    revisarlo (ver docs/dia-5-consola-websocket.md §5.5).

    La detección se hace dentro del contenedor, así que funciona con
    cualquier imagen sin configurar nada: si no hay `bash`, se usa `sh`
    igual que antes. `CTF_CONSOLE_SHELL` fuerza uno concreto.
    """
    shell = shell or getattr(settings, "CTF_CONSOLE_SHELL", "") or None
    if shell:
        arranque = f"exec {shell}"
    else:
        arranque = (
            "if command -v bash >/dev/null 2>&1; "
            "then exec bash; else exec /bin/sh; fi"
        )
    return ["/bin/sh", "-c", f"echo $$ > {pid_file}; {arranque}"]


def terminate_console(container_id: str, pid_file: str) -> None:
    """
    Mata el shell de una consola que ya se cerró, y con él todos los
    procesos que el estudiante hubiera dejado corriendo en esa sesión.

    Docker NO termina el proceso de un `exec` cuando se corta la conexión:
    el shell queda vivo durmiendo sobre una terminal que nadie va a leer.
    Medido, cada reconexión sumaba un proceso contra el `PidsLimit` del
    contenedor, así que tras unas 55 recargas el estudiante se quedaba sin
    poder ejecutar nada dentro de su propio reto.

    Se usa SIGKILL a propósito: un shell interactivo **ignora** SIGTERM —es
    lo que impide que Ctrl-C lo mate— así que un `kill` normal no surtía
    ningún efecto.

    Se mata por SESIÓN, no por grupo de procesos. El intento anterior
    (`kill -9 -$PID`, matar el grupo) NO alcanzaba a los trabajos en
    segundo plano: bash, con control de trabajos, pone cada `cmd &` en su
    PROPIO grupo de procesos, distinto del de la consola (verificado: un
    `sleep 300 &` sobrevivía como huérfano hasta que el watchdog reciclaba
    toda la instancia). En cambio todos comparten la misma SESIÓN, cuyo id
    es el PID de la consola (es el líder de sesión, por tener el pty). Se
    recorre `/proc`, se juntan los procesos con ese `sid` y se los mata.
    Esto sí cubre `cmd &` y subshells detachados como `(cmd &)`.

    Dos riesgos residuales conocidos, ambos aceptados y delegados al
    watchdog (misma política que el resto del SDD: lo que no se puede
    cerrar desde adentro del contenedor se declara asumido, no se finge
    resuelto):

    1. `setsid cmd`: un proceso que se detache a una sesión NUEVA a
       propósito queda con un `sid` distinto y escapa a este barrido.
    2. Carrera TOCTOU: entre que se lee `/proc` y se manda el `kill`, un
       `fork()` puede crear un nieto que no estaba en la lista y sobrevive.
       Probabilidad bajísima (ventana de milisegundos).

    En ambos casos la red de última instancia es el watchdog, que destruye
    el contenedor entero por inactividad / vida máxima.

    El `sid` está en el campo 6 de `/proc/PID/stat`, pero el campo 2
    (`comm`) puede traer espacios o paréntesis, así que se corta el texto
    después del ÚLTIMO `") "`: como ningún campo posterior contiene `) `,
    ese siempre es el paréntesis que cierra `comm`, sin importar cómo se
    llame el proceso.

    Es una limpieza best-effort: si el archivo ya no está, no pasa nada.
    """
    kill_por_sesion = (
        "p=$(cat " + pid_file + " 2>/dev/null); rm -f " + pid_file + "; "
        '[ -z "$p" ] && exit 0; '
        "for d in /proc/[0-9]*; do "
        's=$(cat "$d/stat" 2>/dev/null) || continue; '
        'after=${s##*") "}; '
        "set -- $after; "
        '[ "$4" = "$p" ] && kill -9 "${d#/proc/}" 2>/dev/null; '
        "done; "
        'kill -9 "$p" 2>/dev/null; true'
    )
    exec_id = create_exec(
        container_id,
        cmd=["/bin/sh", "-c", kill_por_sesion],
        tty=False,
        attach=False,
    )
    response = _session().post(
        f"{BASE_URL}/exec/{exec_id}/start", json={"Detach": True, "Tty": False}
    )
    if response.status_code not in (200, 201):
        raise DockerClientError(
            f"No se pudo limpiar la consola de {container_id[:12]}: {response.text}"
        )


def resize_exec(exec_id: str, rows: int, cols: int) -> None:
    """
    Ajusta el tamaño del TTY del exec. Sin esto el proceso dentro del
    contenedor cree que la terminal mide 80x24 y cualquier programa de
    pantalla completa (top, vim) se dibuja mal.
    """
    response = _session().post(
        f"{BASE_URL}/exec/{exec_id}/resize", params={"h": rows, "w": cols}
    )
    if response.status_code != 200:
        raise DockerClientError(
            f"No se pudo redimensionar el exec {exec_id}: {response.text}"
        )


class HijackedExecSocket:
    """
    Envoltorio sobre el socket Unix crudo que queda tras hacer el hijack de
    `POST /exec/{id}/start`. A partir de ahí, todo lo que se envía y recibe
    por este socket son los bytes crudos de stdin/stdout del proceso dentro
    del contenedor (ver SDD 4.4 y 5.2).

    El socket queda en modo NO BLOQUEANTE y la lectura/escritura la atiende
    el bucle de asyncio. Esto es deliberado: leerlo con un hilo por consola
    (`asyncio.to_thread(sock.recv, ...)`) dejaba un hilo bloqueado de forma
    permanente por cada sesión abierta. Como el pool tiene un máximo de
    `min(32, CPUs + 4)` hilos, la plataforma se quedaba sin hilos alrededor
    de las 16 consolas, y los de las conexiones caídas no se liberaban nunca
    porque cancelar la tarea no interrumpe a un hilo ya bloqueado en recv().
    Con `sock_recv`/`sock_sendall` no hay hilos de por medio y la
    cancelación es inmediata.
    """

    def __init__(self, sock: socket.socket):
        sock.setblocking(False)
        self._sock = sock

    async def send(self, data: bytes) -> None:
        if self._sock is None:
            raise OSError("El socket del exec ya fue cerrado")
        await asyncio.get_running_loop().sock_sendall(self._sock, data)

    async def recv(self, bufsize: int = 4096) -> bytes:
        if self._sock is None:
            return b""
        return await asyncio.get_running_loop().sock_recv(self._sock, bufsize)

    def close(self) -> None:
        """
        Idempotente a propósito: si se cerrara dos veces, el descriptor
        liberado podría haber sido reasignado por el kernel a otra
        conexión y estaríamos cerrando la sesión de otro usuario.
        """
        if self._sock is None:
            return
        sock, self._sock = self._sock, None
        # shutdown() desbloquea a cualquier hilo esperando en recv();
        # close() a secas no lo garantiza.
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()


def start_exec_hijacked(exec_id: str) -> HijackedExecSocket:
    """
    Abre un socket Unix propio (independiente de `requests-unixsocket`),
    manda a mano la petición HTTP de `POST /exec/{id}/start` pidiendo
    upgrade de la conexión, y devuelve el socket ya "secuestrado" para
    intercambiar bytes bidireccionalmente con el proceso.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(_docker_socket_path())

    body = json.dumps({"Detach": False, "Tty": True}).encode()
    request = (
        f"POST /exec/{exec_id}/start HTTP/1.1\r\n"
        "Host: docker\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: Upgrade\r\n"
        "Upgrade: tcp\r\n"
        "\r\n"
    ).encode() + body

    try:
        sock.sendall(request)

        # Consumimos la cabecera HTTP de la respuesta (101 Switching
        # Protocols) byte a byte hasta el separador \r\n\r\n; a partir de
        # ahí el socket queda crudo.
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(1)
            if not chunk:
                raise DockerClientError(
                    "El daemon de Docker cerró la conexión antes de completar el hijack"
                )
            buffer += chunk

        status_line = buffer.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in status_line and " 200 " not in status_line:
            raise DockerClientError(f"Hijack de exec falló: {status_line}")
    except Exception:
        sock.close()
        raise

    return HijackedExecSocket(sock)
