#!/usr/bin/env python3
"""
PRUEBA DE CARGA - Plataforma CTF

Simula N estudiantes usando la plataforma a la vez, contra el servidor
real (Daphne) y contenedores reales. Mide:

  1. Tiempo de despliegue de instancias en concurrencia.
  2. Consolas WebSocket simultaneas realmente funcionales.
  3. Hilos consumidos por el servidor (la metrica que delato el techo
     historico de ~16 consolas).
  4. Recursos del host con la carga puesta.
  5. Tiempo de liberacion de todos los recursos.

Uso:
    # con Daphne ya corriendo en 127.0.0.1:8000
    ~/.venvs/ctf-platform/bin/python pruebas/carga.py [usuarios]
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ctf_platform.settings")
os.environ.setdefault("CTF_WATCHDOG_INTEGRADO", "0")

import django  # noqa: E402

django.setup()

import requests  # noqa: E402
import websockets  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402

from ctf.models import Instance  # noqa: E402

BASE = "http://127.0.0.1:8000"
WS_BASE = "ws://127.0.0.1:8000/ws/terminal/"
USUARIOS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
CLAVE = "carga-de-prueba-2026"
PREFIJO = "carga"
RETO = "injection-sqli"


def bloque(codigo, titulo):
    print("\n" + "=" * 72)
    print("[%s] %s" % (codigo, titulo))
    print("=" * 72)


def comando(texto):
    print("  $ %s" % texto)


def linea(texto):
    print("    %s" % texto)


# ---------------------------------------------------------------------
# Instrumentacion del servidor
# ---------------------------------------------------------------------

def pid_daphne():
    salida = subprocess.run(
        ["ps", "-eo", "pid,args"], capture_output=True, text=True
    ).stdout
    for fila in salida.splitlines():
        # Se exige la ruta del ejecutable para no confundirse con shells
        # que solo mencionan "daphne" en su linea de comandos.
        if "bin/daphne" in fila and "grep" not in fila and "bash -lc" not in fila:
            return fila.split()[0]
    return None


def hilos_daphne(pid):
    """Numero de hilos y en que estan bloqueados."""
    if not pid:
        return 0, {}
    try:
        with open("/proc/%s/status" % pid) as fh:
            total = int(re.search(r"Threads:\s+(\d+)", fh.read()).group(1))
    except Exception:  # noqa: BLE001
        return 0, {}

    estados = {}
    try:
        for tarea in os.listdir("/proc/%s/task" % pid):
            try:
                with open("/proc/%s/task/%s/wchan" % (pid, tarea)) as fh:
                    estado = fh.read().strip() or "(corriendo)"
                estados[estado] = estados.get(estado, 0) + 1
            except OSError:
                continue
    except OSError:
        pass
    return total, estados


def sockets_a_docker(pid):
    if not pid:
        return 0
    try:
        salida = subprocess.run(
            ["ls", "-l", "/proc/%s/fd" % pid], capture_output=True, text=True
        ).stdout
        return salida.count("socket:")
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------
# Cliente de un estudiante
# ---------------------------------------------------------------------

class Estudiante:
    def __init__(self, indice):
        self.indice = indice
        self.usuario = "%s%02d" % (PREFIJO, indice)
        self.sesion = requests.Session()
        self.cookie = None
        self.error = None

    def login(self):
        self.sesion.get("%s/login/" % BASE, timeout=30)
        token = self.sesion.cookies.get("csrftoken", "")
        respuesta = self.sesion.post(
            "%s/login/" % BASE,
            data={
                "username": self.usuario,
                "password": CLAVE,
                "csrfmiddlewaretoken": token,
            },
            headers={"Referer": "%s/login/" % BASE},
            timeout=30,
            allow_redirects=True,
        )
        self.cookie = self.sesion.cookies.get("sessionid")
        if not self.cookie:
            self.error = "login fallido (%s)" % respuesta.status_code
        return bool(self.cookie)

    def _cabeceras(self):
        return {
            "X-CSRFToken": self.sesion.cookies.get("csrftoken", ""),
            "Referer": BASE + "/",
            "Content-Type": "application/json",
        }

    def desplegar(self):
        inicio = time.time()
        respuesta = self.sesion.post(
            "%s/api/instance/start/" % BASE,
            data=json.dumps({"challenge": RETO}),
            headers=self._cabeceras(),
            timeout=120,
        )
        tardanza = time.time() - inicio
        if respuesta.status_code != 201:
            self.error = "start -> %s %s" % (
                respuesta.status_code, respuesta.text[:80]
            )
        return respuesta.status_code, tardanza

    def detener(self):
        inicio = time.time()
        respuesta = self.sesion.post(
            "%s/api/instance/stop/" % BASE,
            headers=self._cabeceras(),
            timeout=120,
        )
        return respuesta.status_code, time.time() - inicio


async def usar_consola(estudiante, resultados, soltar=None):
    """
    Abre la consola, ejecuta un comando y comprueba que responde.

    Si se pasa `soltar` (un asyncio.Event), la consola queda ABIERTA y en
    reposo hasta que se active. Eso permite medir los hilos del servidor
    en el escenario realista -- varios estudiantes con la terminal
    abierta sin teclear -- y no solo durante el arranque.
    """
    marca = "CARGA-OK-%02d" % estudiante.indice
    cabeceras = {"Cookie": "sessionid=%s" % estudiante.cookie}
    inicio = time.time()

    async def esperar_cierre():
        if soltar is not None:
            try:
                await asyncio.wait_for(soltar.wait(), timeout=90)
            except asyncio.TimeoutError:
                pass

    try:
        try:
            conexion = await websockets.connect(
                WS_BASE, additional_headers=cabeceras, open_timeout=60
            )
        except TypeError:  # versiones antiguas de la libreria
            conexion = await websockets.connect(
                WS_BASE, extra_headers=cabeceras, open_timeout=60
            )

        async with conexion as ws:
            await asyncio.sleep(1.0)
            await ws.send(("echo %s\n" % marca).encode())

            acumulado = b""
            limite = time.time() + 25
            while time.time() < limite:
                try:
                    trozo = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    break
                acumulado += trozo if isinstance(trozo, bytes) else trozo.encode()
                # El eco del comando tambien contiene la marca: se exige
                # verla dos veces (lo tecleado + lo que imprime el shell).
                if acumulado.count(marca.encode()) >= 2:
                    resultados.append(
                        (estudiante.indice, True, time.time() - inicio, "")
                    )
                    await esperar_cierre()
                    return
            resultados.append(
                (estudiante.indice, False, time.time() - inicio, "sin eco del comando")
            )
            await esperar_cierre()
    except Exception as exc:  # noqa: BLE001
        resultados.append(
            (estudiante.indice, False, time.time() - inicio, type(exc).__name__)
        )


# ---------------------------------------------------------------------

def main():
    print("PRUEBA DE CARGA - PLATAFORMA CTF")
    print("Fecha: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("Estudiantes simulados: %d" % USUARIOS)
    print("Reto desplegado por cada uno: %s" % RETO)

    pid = pid_daphne()
    if not pid:
        print("\nERROR: Daphne no esta corriendo en este equipo.")
        return 2
    print("PID de Daphne: %s" % pid)

    # -----------------------------------------------------------------
    bloque("C-00", "PREPARACION: cuentas de estudiante y estado inicial")
    comando("User.objects.create_user(...) x %d" % USUARIOS)
    creadas = 0
    for i in range(1, USUARIOS + 1):
        nombre = "%s%02d" % (PREFIJO, i)
        usuario, nueva = User.objects.get_or_create(username=nombre)
        usuario.set_password(CLAVE)
        usuario.save()
        creadas += 1 if nueva else 0
    linea("Cuentas listas: %d (nuevas: %d)" % (USUARIOS, creadas))

    Instance.objects.filter(user__username__startswith=PREFIJO).delete()
    hilos_ini, estados_ini = hilos_daphne(pid)
    linea("Hilos del servidor en reposo: %d" % hilos_ini)
    linea("Sockets abiertos en reposo: %d" % sockets_a_docker(pid))
    linea("Contenedores CTF vivos: %s" % subprocess.run(
        ["sh", "-c", "docker ps -q --filter ancestor=ctf-reto-%s:latest | wc -l" % RETO],
        capture_output=True, text=True).stdout.strip())

    # -----------------------------------------------------------------
    bloque("C-01", "AUTENTICACION CONCURRENTE DE %d ESTUDIANTES" % USUARIOS)
    comando("POST /login/ x %d en paralelo" % USUARIOS)
    estudiantes = [Estudiante(i) for i in range(1, USUARIOS + 1)]
    inicio = time.time()
    with ThreadPoolExecutor(max_workers=USUARIOS) as pool:
        ok_login = list(pool.map(lambda e: e.login(), estudiantes))
    total_login = time.time() - inicio
    linea("Sesiones iniciadas: %d / %d" % (sum(ok_login), USUARIOS))
    linea("Tiempo total: %.2f s" % total_login)
    for e in estudiantes:
        if e.error:
            linea("  %s: %s" % (e.usuario, e.error))

    activos = [e for e in estudiantes if e.cookie]
    if not activos:
        print("\nERROR: ningun estudiante pudo autenticarse.")
        return 2

    # -----------------------------------------------------------------
    bloque("C-02", "DESPLIEGUE CONCURRENTE DE %d INSTANCIAS" % len(activos))
    comando("POST /api/instance/start/ x %d en paralelo" % len(activos))
    inicio = time.time()
    with ThreadPoolExecutor(max_workers=len(activos)) as pool:
        resultados = list(pool.map(lambda e: e.desplegar(), activos))
    total_despliegue = time.time() - inicio

    exitosos = [t for c, t in resultados if c == 201]
    fallidos = [(c, t) for c, t in resultados if c != 201]
    linea("Instancias creadas: %d / %d" % (len(exitosos), len(activos)))
    linea("Tiempo total de la oleada: %.2f s" % total_despliegue)
    if exitosos:
        linea("Latencia por instancia -> min %.2f s | media %.2f s | max %.2f s"
              % (min(exitosos), sum(exitosos) / len(exitosos), max(exitosos)))
    for codigo, _ in fallidos:
        linea("  respuesta inesperada: %s" % codigo)
    for e in activos:
        if e.error:
            linea("  %s: %s" % (e.usuario, e.error))

    en_bd = Instance.objects.filter(user__username__startswith=PREFIJO).count()
    en_docker = subprocess.run(
        ["sh", "-c", "docker ps -q --filter ancestor=ctf-reto-%s:latest | wc -l" % RETO],
        capture_output=True, text=True).stdout.strip()
    linea("Filas en base de datos: %d" % en_bd)
    linea("Contenedores reales en Docker: %s" % en_docker)

    # -----------------------------------------------------------------
    bloque("C-03", "CONSOLAS WEBSOCKET SIMULTANEAS")
    comando("ws://127.0.0.1:8000/ws/terminal/ x %d + 'echo CARGA-OK-nn'" % len(activos))

    consola = []
    hilos_durante = {"total": 0, "estados": {}}
    hilos_reposo = {"total": 0, "estados": {}}
    sockets_durante = {"n": 0}

    async def orquestar():
        soltar = asyncio.Event()
        tareas = [
            asyncio.create_task(usar_consola(e, consola, soltar))
            for e in activos
            if not e.error
        ]
        # T1: durante el arranque, con las llamadas al daemon en vuelo.
        await asyncio.sleep(6)
        hilos_durante["total"], hilos_durante["estados"] = hilos_daphne(pid)
        sockets_durante["n"] = sockets_a_docker(pid)
        # T2: con todas las consolas ya establecidas y en reposo.
        await asyncio.sleep(14)
        hilos_reposo["total"], hilos_reposo["estados"] = hilos_daphne(pid)
        soltar.set()
        await asyncio.gather(*tareas)

    inicio = time.time()
    asyncio.run(orquestar())
    total_consolas = time.time() - inicio

    funcionaron = [c for c in consola if c[1]]
    fallaron = [c for c in consola if not c[1]]
    linea("Consolas que ejecutaron el comando: %d / %d"
          % (len(funcionaron), len(consola)))
    linea("Tiempo total: %.2f s" % total_consolas)
    if funcionaron:
        tiempos = [c[2] for c in funcionaron]
        linea("Respuesta por consola -> min %.2f s | media %.2f s | max %.2f s"
              % (min(tiempos), sum(tiempos) / len(tiempos), max(tiempos)))
    for indice, _, _, motivo in fallaron:
        linea("  consola %02d fallo: %s" % (indice, motivo))

    # -----------------------------------------------------------------
    bloque("C-04", "CONSUMO DE HILOS DEL SERVIDOR (metrica critica)")
    comando("cat /proc/%s/status | grep Threads" % pid)
    linea("Hilos en reposo            : %d" % hilos_ini)
    linea("Hilos con %d consolas abiertas: %d" % (len(consola), hilos_reposo["total"]))
    crecimiento = hilos_reposo["total"] - hilos_ini
    linea("Crecimiento: %+d hilos para %d consolas" % (crecimiento, len(consola)))
    if len(consola):
        linea("Hilos por consola: %.2f" % (crecimiento / len(consola)))

    def contar_bloqueados(estados):
        return sum(
            n for e, n in estados.items()
            if "unix_stream" in e or "stream_read" in e
        )

    comando("for t in /proc/%s/task/*; do cat $t/wchan; done | sort | uniq -c" % pid)
    linea("")
    linea("T1 - durante el arranque de las consolas (llamadas al daemon en vuelo):")
    for estado, cuantos in sorted(
        hilos_durante["estados"].items(), key=lambda x: -x[1]
    ):
        linea("  %4d  %s" % (cuantos, estado))
    bloqueados_t1 = contar_bloqueados(hilos_durante["estados"])
    linea("  bloqueados en E/S de socket: %d" % bloqueados_t1)

    linea("")
    linea("T2 - con las %d consolas ya abiertas y en reposo:" % len(consola))
    for estado, cuantos in sorted(
        hilos_reposo["estados"].items(), key=lambda x: -x[1]
    ):
        linea("  %4d  %s" % (cuantos, estado))
    bloqueados = contar_bloqueados(hilos_reposo["estados"])
    linea("  bloqueados en E/S de socket: %d" % bloqueados)
    linea("")
    linea("Hilos totales: reposo %d -> arranque %d -> consolas abiertas %d"
          % (hilos_ini, hilos_durante["total"], hilos_reposo["total"]))
    linea("Lectura: si cada consola consumiera un hilo propio, con %d consolas"
          % len(consola))
    linea("habria al menos %d hilos bloqueados de forma permanente." % len(consola))
    linea("Sockets abiertos por el servidor: %d (en reposo eran %d)"
          % (sockets_durante["n"], sockets_a_docker(pid)))

    # -----------------------------------------------------------------
    bloque("C-05", "RECURSOS DEL HOST BAJO CARGA")
    comando("docker stats --no-stream")
    stats = subprocess.run(
        ["sh", "-c",
         "docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' "
         "$(docker ps -q --filter ancestor=ctf-reto-%s:latest) 2>/dev/null | head -5" % RETO],
        capture_output=True, text=True).stdout.strip()
    for fila in stats.splitlines():
        linea(fila)
    linea("... (se muestran las primeras 5 de %s)" % en_docker)

    mem_total = subprocess.run(
        ["sh", "-c",
         "docker stats --no-stream --format '{{.MemUsage}}' "
         "$(docker ps -q --filter ancestor=ctf-reto-%s:latest) 2>/dev/null "
         "| awk '{print $1}' | sed 's/MiB//' | paste -sd+ | bc" % RETO],
        capture_output=True, text=True).stdout.strip()
    linea("Memoria sumada de los %s contenedores: %s MiB" % (en_docker, mem_total or "?"))
    comando("free -m")
    for fila in subprocess.run(
        ["sh", "-c", "free -m | sed -n '1p;2p'"], capture_output=True, text=True
    ).stdout.strip().splitlines():
        linea(fila)

    # -----------------------------------------------------------------
    bloque("C-06", "LIBERACION DE RECURSOS")
    comando("POST /api/instance/stop/ x %d en paralelo" % len(activos))
    inicio = time.time()
    with ThreadPoolExecutor(max_workers=len(activos)) as pool:
        cierres = list(pool.map(lambda e: e.detener(), activos))
    total_cierre = time.time() - inicio
    detenidas = [t for c, t in cierres if c == 200]
    linea("Instancias detenidas: %d / %d" % (len(detenidas), len(activos)))
    linea("Tiempo total: %.2f s" % total_cierre)
    if detenidas:
        linea("Latencia por destruccion -> media %.2f s | max %.2f s"
              % (sum(detenidas) / len(detenidas), max(detenidas)))

    time.sleep(2)
    quedan_bd = Instance.objects.filter(user__username__startswith=PREFIJO).count()
    quedan_docker = subprocess.run(
        ["sh", "-c", "docker ps -aq --filter ancestor=ctf-reto-%s:latest | wc -l" % RETO],
        capture_output=True, text=True).stdout.strip()
    quedan_redes = subprocess.run(
        ["sh", "-c", "docker network ls -q --filter name=ctf-net- | wc -l"],
        capture_output=True, text=True).stdout.strip()
    linea("Filas en base de datos tras la limpieza: %d" % quedan_bd)
    linea("Contenedores restantes: %s" % quedan_docker)
    linea("Redes ctf-net-* restantes: %s" % quedan_redes)

    hilos_fin, _ = hilos_daphne(pid)
    linea("Hilos del servidor tras cerrar todo: %d (en reposo eran %d)"
          % (hilos_fin, hilos_ini))

    # -----------------------------------------------------------------
    print("\n" + "=" * 72)
    print("RESUMEN DE LA PRUEBA DE CARGA")
    print("=" * 72)
    filas = [
        ("Estudiantes simulados", str(USUARIOS)),
        ("Sesiones iniciadas", "%d / %d" % (sum(ok_login), USUARIOS)),
        ("Instancias desplegadas", "%d / %d" % (len(exitosos), len(activos))),
        ("Tiempo de la oleada de despliegue", "%.2f s" % total_despliegue),
        ("Latencia media por instancia",
         "%.2f s" % (sum(exitosos) / len(exitosos)) if exitosos else "-"),
        ("Consolas simultaneas funcionales",
         "%d / %d" % (len(funcionaron), len(consola))),
        ("Hilos del servidor en reposo", str(hilos_ini)),
        ("Hilos con todas las consolas abiertas", str(hilos_reposo["total"])),
        ("Hilos consumidos por consola",
         "%.2f" % (crecimiento / len(consola)) if consola else "-"),
        ("Hilos bloqueados en E/S", str(bloqueados)),
        ("Instancias liberadas", "%d / %d" % (len(detenidas), len(activos))),
        ("Residuos tras la limpieza",
         "%d filas / %s contenedores" % (quedan_bd, quedan_docker)),
    ]
    for etiqueta, valor in filas:
        print("  %-42s %s" % (etiqueta, valor))

    todo_ok = (
        len(exitosos) == len(activos)
        and len(funcionaron) == len(consola)
        and quedan_bd == 0
    )
    print("\n  VEREDICTO: %s" % ("OK" if todo_ok else "CON INCIDENCIAS"))
    return 0 if todo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
