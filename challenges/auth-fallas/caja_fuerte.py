#!/usr/bin/env python3
"""
Caja fuerte protegida por un PIN de 4 dígitos (OWASP A07:2021 -
Identification and Authentication Failures). El PIN por sí solo no es
el problema -- es que no hay límite de intentos, ni bloqueo, ni demora:
se puede probar los 10.000 valores posibles sin ninguna fricción.
"""

import sys

PIN_PATH = "/app/pin.txt"


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(f"uso: {sys.argv[0]} <pin de 4 digitos>")
        sys.exit(1)

    with open(PIN_PATH) as f:
        pin_correcto = f.read().strip()

    if sys.argv[1].zfill(4) == pin_correcto:
        print("PIN correcto. Caja fuerte abierta.")
        with open("/app/flag.txt") as f:
            print(f.read().strip())
    else:
        print("PIN incorrecto.")


if __name__ == "__main__":
    main()
