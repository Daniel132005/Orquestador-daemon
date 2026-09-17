#!/usr/bin/env python3
"""
Portal que autentica por token de sesión (OWASP A09:2021 - Security
Logging and Monitoring Failures). Los tokens se registraron en texto
plano en /home/retador/sesiones.log y nadie los rota ni monitorea esa
fuga: ese archivo, con permisos por defecto, es legible por cualquiera.
No hay ninguna alerta ni revisión que hubiera detectado el problema.
"""

import json
import sys

TOKENS_PATH = "/app/tokens.json"


def main():
    if len(sys.argv) != 2:
        print(f"uso: {sys.argv[0]} <token>")
        sys.exit(1)

    token = sys.argv[1]
    with open(TOKENS_PATH) as f:
        tokens = json.load(f)

    usuario = next((u for u, t in tokens.items() if t == token), None)
    if usuario is None:
        print("Token inválido.")
        return

    print(f"Sesión válida para: {usuario}")
    if usuario == "admin":
        with open("/app/flag.txt") as f:
            print(f.read().strip())


if __name__ == "__main__":
    main()
