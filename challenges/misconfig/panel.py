#!/usr/bin/env python3
"""
Panel de administración (OWASP A05:2021 - Security Misconfiguration).
Las credenciales reales están bien protegidas (root, modo 600) -- el
problema es que quedó una copia de respaldo del archivo de configuración
sin borrar y con permisos por defecto, legible por cualquiera.
"""

import json
import sys

CREDENCIALES_PATH = "/app/credenciales.json"


def main():
    if len(sys.argv) != 3:
        print(f"uso: {sys.argv[0]} <usuario> <clave>")
        sys.exit(1)

    usuario, clave = sys.argv[1], sys.argv[2]
    with open(CREDENCIALES_PATH) as f:
        credenciales = json.load(f)

    if credenciales.get("admin_user") == usuario and credenciales.get("admin_pass") == clave:
        print(f"Acceso concedido. Bienvenido, {usuario}.")
        with open("/app/flag.txt") as f:
            print(f.read().strip())
    else:
        print("Credenciales incorrectas.")


if __name__ == "__main__":
    main()
