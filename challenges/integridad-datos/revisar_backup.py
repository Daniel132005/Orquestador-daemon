#!/usr/bin/env python3
"""
Revisor de backups (OWASP A08:2021 - Software and Data Integrity
Failures): deserializa con `pickle.load()` un archivo que cualquiera
puede escribir, sin verificar firma ni integridad. `pickle` puede
ejecutar código arbitrario al deserializar -- por diseño, no por bug --
así que confiar en un archivo que no se puede garantizar que no fue
alterado es el error, no la librería en sí.

Corre con privilegios de root vía sudo (ver Dockerfile), así que
cualquier código que se ejecute al deserializar corre como root.
"""

import pickle

BACKUP_PATH = "/tmp/backup.dat"


def main():
    try:
        with open(BACKUP_PATH, "rb") as f:
            datos = pickle.load(f)
    except FileNotFoundError:
        print(f"No hay backup en {BACKUP_PATH}. Generá uno primero.")
        return

    print(f"Backup revisado. Contenido: {datos!r}")


if __name__ == "__main__":
    main()
