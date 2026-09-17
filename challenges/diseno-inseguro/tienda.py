#!/usr/bin/env python3
"""
Tienda con una falla de diseño (OWASP A04:2021 - Insecure Design): un
cupón de descuento válido se puede aplicar tantas veces como se quiera
en la misma compra. No es un bug de código (el descuento se resta bien
cada vez); es que nunca se diseñó una regla de negocio que impida
reusar el mismo cupón, ni que impida que el saldo baje de cero.
"""

import sys

SALDO_INICIAL = 50
DESCUENTO_POR_USO = 10
CODIGOS_VALIDOS = {"BIENVENIDA10"}


def main():
    codigos = sys.argv[1:]
    if not codigos:
        print(f"uso: {sys.argv[0]} <codigo_cupon> [<codigo_cupon> ...]")
        return

    saldo = SALDO_INICIAL
    aplicados = 0
    for codigo in codigos:
        if codigo in CODIGOS_VALIDOS:
            saldo -= DESCUENTO_POR_USO
            aplicados += 1

    print(f"Cupones válidos aplicados: {aplicados}. Saldo pendiente: ${saldo}")

    if saldo <= 0:
        with open("/app/flag.txt") as f:
            print(f"Cuenta liquidada -- acceso VIP desbloqueado: {f.read().strip()}")


if __name__ == "__main__":
    main()
