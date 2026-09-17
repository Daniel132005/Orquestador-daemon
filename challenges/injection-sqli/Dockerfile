# Reto: login vulnerable a SQL injection (OWASP A03:2021 - Injection).
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-injection-sqli:latest challenges/injection-sqli/
#
# La base se genera en tiempo de build (clave de admin aleatoria, ver
# setup_db.py) y `setup_db.py` se borra después.
#
# `retador` (el usuario de la consola) no puede leer `flag.txt` ni la
# base directamente: son de `root`, modo 600. Solo puede correr la app
# como root vía el `sudo` restringido de más abajo — ni un comando más.
# Sin esto, `cat flag.txt` resolvía el reto sin inyectar nada.

FROM ctf-base:latest

WORKDIR /app
USER root

COPY setup_db.py .
RUN python3 setup_db.py && rm setup_db.py
COPY app.py flag.txt ./

RUN chown root:root app.py flag.txt usuarios.db \
    && chmod 600 flag.txt usuarios.db \
    && chmod 755 app.py \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/app.py' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
