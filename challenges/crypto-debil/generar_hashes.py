"""Genera el archivo de hashes en tiempo de build. La clave de admin es
deliberadamente débil (está en wordlist.txt) para que el reto se resuelva
probando contraseñas comunes contra un hash MD5 sin sal -- exactamente
el error de OWASP A02: usar un algoritmo débil y sin sal para credenciales."""

import hashlib

CLAVE_ADMIN = "primavera2023"  # está en wordlist.txt a propósito

with open("/app/hashes.txt", "w") as f:
    f.write(f"invitado:{hashlib.md5(b'invitado').hexdigest()}\n")
    f.write(f"admin:{hashlib.md5(CLAVE_ADMIN.encode()).hexdigest()}\n")
