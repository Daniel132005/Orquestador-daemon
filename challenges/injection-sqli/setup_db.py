"""Crea la base de datos del reto en tiempo de build, con una clave de
admin larga y aleatoria: si alguien la adivinara por fuerza bruta en vez
de inyectar SQL, no seria la via pensada para el reto, pero tampoco
seria posible en la practica."""

import secrets
import sqlite3

con = sqlite3.connect("/app/usuarios.db")
cur = con.cursor()
cur.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, usuario TEXT, clave TEXT)")
cur.execute(
    "INSERT INTO usuarios (usuario, clave) VALUES (?, ?)",
    ("invitado", "invitado123"),
)
cur.execute(
    "INSERT INTO usuarios (usuario, clave) VALUES (?, ?)",
    ("admin", secrets.token_hex(32)),
)
con.commit()
con.close()
