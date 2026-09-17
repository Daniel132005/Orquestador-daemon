"""Genera un PIN de 4 digitos al azar en tiempo de build. 10.000
combinaciones son pocas si nada limita los intentos -- ese es el punto."""

import secrets

with open("/app/pin.txt", "w") as f:
    f.write(f"{secrets.randbelow(10000):04d}")
