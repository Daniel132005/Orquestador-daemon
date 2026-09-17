# Reto: deserialización insegura con pickle (OWASP A08:2021 - Software
# and Data Integrity Failures). Dificultad: difícil.
#
# /tmp es tmpfs con rw (ver docker_client.create_container): retador
# puede escribir ahí un pickle malicioso y `revisar_backup.py`, corrido
# como root vía sudo, lo va a deserializar sin chequear nada.
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-integridad-datos:latest challenges/integridad-datos/

FROM ctf-base:latest

WORKDIR /app
USER root

COPY revisar_backup.py flag.txt ./

RUN chown root:root revisar_backup.py flag.txt \
    && chmod 600 flag.txt \
    && chmod 755 revisar_backup.py \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/revisar_backup.py' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
