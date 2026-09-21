#!/usr/bin/env python3
"""
PRUEBAS DE HUMO - Plataforma CTF

Verifican que las piezas criticas del sistema funcionan de extremo a
extremo contra el Docker Engine REAL (no hay dobles de prueba aqui).
Ejercitan el cliente Docker propio del proyecto, `ctf/docker_client.py`.

Uso:
    ~/.venvs/ctf-platform/bin/python pruebas/humo.py

Requiere: Docker corriendo y las imagenes de los retos construidas.
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ctf_platform.settings")
os.environ.setdefault("CTF_WATCHDOG_INTEGRADO", "0")

import django  # noqa: E402

django.setup()

from ctf import challenges, docker_client  # noqa: E402

IMAGEN = "ctf-reto-idor:latest"
MEM_BYTES = 256 * 1024 * 1024
NANO_CPUS = 500_000_000
PIDS_LIMIT = 64

resultados = []


def bloque(codigo, titulo):
    print("\n" + "=" * 72)
    print("[%s] %s" % (codigo, titulo))
    print("=" * 72)


def comando(texto):
    print("  $ %s" % texto)


def salida(texto):
    for linea in str(texto).rstrip().splitlines():
        print("    %s" % linea)


def veredicto(codigo, ok, detalle=""):
    estado = "OK" if ok else "FALLO"
    print("  >> RESULTADO: %s%s" % (estado, (" - " + detalle) if detalle else ""))
    resultados.append((codigo, ok))
    return ok


def docker_exec(container_id, cmd, user=None):
    """Lee el estado real dentro del contenedor (verificacion externa)."""
    base = ["docker", "exec"]
    if user:
        base += ["-u", user]
    base += [container_id] + cmd
    proceso = subprocess.run(base, capture_output=True, text=True, timeout=30)
    return proceso.stdout.strip(), proceso.stderr.strip(), proceso.returncode


def main():
    print("PRUEBAS DE HUMO - PLATAFORMA CTF")
    print("Fecha: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("Docker Engine: real  |  Dobles de prueba: ninguno")

    red_id = None
    contenedor_id = None

    try:
        # ------------------------------------------------------------------
        bloque("H-01", "El cliente Docker propio crea una red aislada")
        nombre_red = "ctf-net-humo-%d" % int(time.time())
        comando("docker_client.create_network('%s')" % nombre_red)
        inicio = time.time()
        red_id = docker_client.create_network(nombre_red)
        tardanza = time.time() - inicio
        salida("Id de red: %s" % red_id[:12])
        salida("Tiempo: %.3f s" % tardanza)

        insp = subprocess.run(
            ["docker", "network", "inspect", red_id, "--format",
             "Internal={{.Internal}} Driver={{.Driver}}"],
            capture_output=True, text=True,
        ).stdout.strip()
        salida("Inspeccion: %s" % insp)
        veredicto("H-01", "Internal=true" in insp, "red sin salida a internet")

        # ------------------------------------------------------------------
        bloque("H-02", "Crea el contenedor del reto con limites de recursos")
        comando("docker_client.create_container(image=%s, mem=256MB, cpus=0.5, pids=64)"
                % IMAGEN)
        inicio = time.time()
        contenedor_id = docker_client.create_container(
            image=IMAGEN,
            network_name=nombre_red,
            mem_limit_bytes=MEM_BYTES,
            nano_cpus=NANO_CPUS,
            pids_limit=PIDS_LIMIT,
        )
        salida("Id de contenedor: %s" % contenedor_id[:12])
        salida("Tiempo: %.3f s" % (time.time() - inicio))
        veredicto("H-02", bool(contenedor_id))

        # ------------------------------------------------------------------
        bloque("H-03", "Inyecta la bandera personalizada del estudiante")
        flag = challenges.generate_dynamic_flag(user_id=1, slug="idor")
        comando("docker_client.inject_challenge_flag(cont, 'idor', <flag del alumno 1>)")
        docker_client.inject_challenge_flag(contenedor_id, "idor", flag)
        salida("Bandera generada: %s" % flag)
        veredicto("H-03", flag.startswith("FLAG{"))

        # ------------------------------------------------------------------
        bloque("H-04", "Arranca el contenedor")
        comando("docker_client.start_container(cont)")
        inicio = time.time()
        docker_client.start_container(contenedor_id)
        salida("Tiempo: %.3f s" % (time.time() - inicio))
        estado = subprocess.run(
            ["docker", "inspect", contenedor_id, "--format", "{{.State.Status}}"],
            capture_output=True, text=True,
        ).stdout.strip()
        salida("Estado del contenedor: %s" % estado)
        veredicto("H-04", estado == "running")

        # ------------------------------------------------------------------
        bloque("H-05", "Los limites llegaron al kernel (vistos desde dentro)")
        comando("docker exec <cont> cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/pids.max")
        mem, _, _ = docker_exec(contenedor_id, ["cat", "/sys/fs/cgroup/memory.max"])
        pids, _, _ = docker_exec(contenedor_id, ["cat", "/sys/fs/cgroup/pids.max"])
        cpu, _, _ = docker_exec(contenedor_id, ["cat", "/sys/fs/cgroup/cpu.max"])
        salida("memory.max = %s  (esperado %d)" % (mem, MEM_BYTES))
        salida("pids.max   = %s  (esperado %d)" % (pids, PIDS_LIMIT))
        salida("cpu.max    = %s  (esperado 50000 100000 = 0.5 CPU)" % cpu)
        veredicto(
            "H-05",
            mem == str(MEM_BYTES) and pids == str(PIDS_LIMIT),
            "cgroups aplicados por el kernel",
        )

        # ------------------------------------------------------------------
        bloque("H-06", "La bandera NO es legible por el usuario sin privilegios")
        comando("docker exec -u retador <cont> cat /app/pedidos.json")
        out, err, codigo = docker_exec(
            contenedor_id, ["cat", "/app/pedidos.json"], user="retador"
        )
        salida(err or out or "(sin salida)")
        salida("Codigo de salida: %d" % codigo)
        sin_acceso = codigo != 0 and flag not in out
        veredicto("H-06", sin_acceso, "hay que explotar la falla para obtenerla")

        # ------------------------------------------------------------------
        bloque("H-07", "La bandera SI es accesible explotando el reto (via sudo)")
        comando("docker exec -u retador <cont> sudo /usr/bin/python3 /app/pedidos.py 1337")
        out, err, codigo = docker_exec(
            contenedor_id,
            ["sudo", "/usr/bin/python3", "/app/pedidos.py", "1337"],
            user="retador",
        )
        salida(out or err or "(sin salida)")
        veredicto("H-07", flag in out, "el reto es resoluble")

        # ------------------------------------------------------------------
        bloque("H-08", "La consola interactiva puede abrirse (exec del TTY)")
        comando("docker_client.create_exec(cont, ['/bin/sh'])")
        exec_id = docker_client.create_exec(contenedor_id, ["/bin/sh"])
        salida("Id del exec: %s" % exec_id[:12])
        veredicto("H-08", bool(exec_id))

        # ------------------------------------------------------------------
        bloque("H-09", "El contenedor aparece en el inventario de la plataforma")
        comando("docker_client.list_ctf_containers()")
        inventario = docker_client.list_ctf_containers()
        ids = [c.get("container_id", "")[:12] for c in inventario]
        salida("Contenedores CTF vivos: %d" % len(inventario))
        salida("Ids: %s" % (", ".join(ids) or "(ninguno)"))
        for fila in inventario:
            if fila.get("container_id", "").startswith(contenedor_id[:12]):
                salida("Imagen: %s | Estado: %s | Red: %s"
                       % (fila["image"], fila["state"], fila["network_name"]))
        veredicto("H-09", contenedor_id[:12] in ids,
                  "el panel puede detectar huerfanos")

        # ------------------------------------------------------------------
        bloque("H-10", "Destruccion completa: contenedor y red")
        comando("docker_client.destroy_instance(cont, red)")
        inicio = time.time()
        docker_client.destroy_instance(contenedor_id, red_id)
        salida("Tiempo: %.3f s" % (time.time() - inicio))

        quedan_cont = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "id=%s" % contenedor_id],
            capture_output=True, text=True,
        ).stdout.strip()
        quedan_red = subprocess.run(
            ["docker", "network", "ls", "-q", "--filter", "id=%s" % red_id],
            capture_output=True, text=True,
        ).stdout.strip()
        salida("Contenedor restante: %s" % (quedan_cont or "ninguno"))
        salida("Red restante: %s" % (quedan_red or "ninguna"))
        limpio = not quedan_cont and not quedan_red
        veredicto("H-10", limpio, "sin residuos en el host")
        if limpio:
            contenedor_id = red_id = None

    finally:
        # Limpieza defensiva si alguna prueba fallo a mitad de camino.
        if contenedor_id or red_id:
            print("\n[limpieza] eliminando recursos de la prueba")
            try:
                docker_client.destroy_instance(contenedor_id, red_id)
            except Exception as exc:  # noqa: BLE001
                print("  aviso: %s" % exc)

    print("\n" + "=" * 72)
    print("RESUMEN DE PRUEBAS DE HUMO")
    print("=" * 72)
    for codigo, ok in resultados:
        print("  %-8s %s" % (codigo, "OK" if ok else "FALLO"))
    fallidas = [c for c, ok in resultados if not ok]
    print("\n  Total: %d  |  Exitosas: %d  |  Fallidas: %d"
          % (len(resultados), len(resultados) - len(fallidas), len(fallidas)))
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
