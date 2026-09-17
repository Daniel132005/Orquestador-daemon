#!/usr/bin/env python3
"""
Generador de vistas previas (OWASP A10:2021 - Server-Side Request
Forgery). Simula un servicio que "busca" una URL por el estudiante --
sin red real, pero con el mismo defecto de fondo que un SSRF real: el
servidor decide a qué recurso interno puede llegar, y la lista negra que
lo bloquea compara el host de forma literal, sensible a mayúsculas.
Alcanza con cambiarle el caso a la URL para saltarla.
"""

import sys

BLOQUEADOS = {"metadata.ctf.local"}
RECURSOS_PUBLICOS = {
    "imagenes.ctf.local": "paisaje.jpg",
    "cdn.ctf.local": "logo.png",
}


def obtener_host(url):
    return url.split("//", 1)[-1].split("/", 1)[0]


def main():
    if len(sys.argv) != 2:
        print(f"uso: {sys.argv[0]} <url>")
        sys.exit(1)

    host = obtener_host(sys.argv[1])

    if host in BLOQUEADOS:
        print(f"Acceso bloqueado: {host} es un recurso interno.")
        return

    if host.lower() == "metadata.ctf.local":
        with open("/app/flag.txt") as f:
            print(f"Vista previa del recurso interno:\n{f.read().strip()}")
        return

    print(f"Vista previa: {RECURSOS_PUBLICOS.get(host, 'recurso desconocido')}")


if __name__ == "__main__":
    main()
