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
import json
import socket

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
            "ReadonlyRootfs": True,
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"},
            "AutoRemove": False,
        },
    }
    response = _check(
        _session().post(f"{BASE_URL}/containers/create", json=payload), (201,)
    )
    return response.json()["Id"]


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


# --- Exec + hijack -----------------------------------------------------


def create_exec(container_id: str, cmd: list[str] | None = None) -> str:
    payload = {
        "AttachStdin": True,
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": True,
        "Cmd": cmd or ["/bin/sh"],
    }
    response = _check(
        _session().post(f"{BASE_URL}/containers/{container_id}/exec", json=payload),
        (201,),
    )
    return response.json()["Id"]


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
