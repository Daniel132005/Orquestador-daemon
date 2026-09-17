#!/usr/bin/env python3
"""
Portal de acceso deliberadamente vulnerable (OWASP A03:2021 - Injection).

La consulta se arma concatenando el texto que escribe quien usa el
programa, sin ninguna sanitización ni consulta parametrizada. Cualquier
comilla dentro de "usuario" o "clave" se interpreta como parte del SQL,
no como dato.
"""

import sqlite3

DB = "/app/usuarios.db"


def login(usuario: str, clave: str):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    consulta = (
        f"SELECT usuario FROM usuarios WHERE usuario = '{usuario}' "
        f"AND clave = '{clave}'"
    )
    cur.execute(consulta)
    fila = cur.fetchone()
    con.close()
    return fila


def main():
    print("=== Portal de acceso ===")
    usuario = input("Usuario: ")
    clave = input("Clave: ")
    fila = login(usuario, clave)
    if fila is None:
        print("Acceso denegado.")
        return
    print(f"Acceso concedido. Bienvenido, {fila[0]}.")
    if fila[0] == "admin":
        with open("/app/flag.txt") as f:
            print(f.read().strip())


if __name__ == "__main__":
    main()
