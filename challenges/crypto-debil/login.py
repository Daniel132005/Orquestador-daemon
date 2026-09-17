#!/usr/bin/env python3
"""
Login vulnerable a OWASP A02:2021 - Cryptographic Failures: las claves
se guardan con MD5 sin sal, un algoritmo roto para contraseñas (rápido
de calcular en masa, sin costo computacional). Alcanza con probar
contraseñas comunes -- están en /home/retador/wordlist.txt -- y
compararlas contra el hash filtrado.
"""

import hashlib
import sys

HASHES_PATH = "/app/hashes.txt"


def cargar_hashes():
    hashes = {}
    with open(HASHES_PATH) as f:
        for linea in f:
            usuario, hash_ = linea.strip().split(":", 1)
            hashes[usuario] = hash_
    return hashes


def main():
    if len(sys.argv) != 3:
        print(f"uso: {sys.argv[0]} <usuario> <clave>")
        sys.exit(1)

    usuario, clave = sys.argv[1], sys.argv[2]
    hashes = cargar_hashes()
    esperado = hashes.get(usuario)
    if esperado is None:
        print("Usuario no encontrado.")
        return

    if hashlib.md5(clave.encode()).hexdigest() == esperado:
        print(f"Acceso concedido. Bienvenido, {usuario}.")
        if usuario == "admin":
            with open("/app/flag.txt") as f:
                print(f.read().strip())
    else:
        print("Clave incorrecta.")


if __name__ == "__main__":
    main()
