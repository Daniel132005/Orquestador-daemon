#!/usr/bin/env python3
"""
libcalc 1.4.2 -- calculadora de expresiones (OWASP A06:2021 - Vulnerable
and Outdated Components).

Esta versión evalúa la expresión con `eval()` sin ninguna restricción,
una falla pública de esta versión (corregida en 2.0.0 con un parser
seguro). Cualquier despliegue que siga usando 1.4.2 hereda el problema:
no es un error de este script en particular, es el componente entero
el que está obsoleto y es inseguro.
"""

import sys

VERSION = "1.4.2"


def main():
    if len(sys.argv) != 2:
        print(f"libcalc {VERSION}")
        print(f"uso: {sys.argv[0]} '<expresion>'")
        sys.exit(1)

    if sys.argv[1] == "--version":
        print(f"libcalc {VERSION} (CVE-2021-99999: eval() sin sandbox, corregido en 2.0.0)")
        return

    resultado = eval(sys.argv[1])
    print(f"Resultado: {resultado}")


if __name__ == "__main__":
    main()
