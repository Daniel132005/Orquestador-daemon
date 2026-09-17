# Reto: token de sesión filtrado en un log sin monitoreo (OWASP
# A09:2021 - Security Logging and Monitoring Failures). Dificultad: intermedio.
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-logging-fallas:latest challenges/logging-fallas/

FROM ctf-base:latest

WORKDIR /app
USER root

COPY portal.py tokens.json flag.txt ./
COPY sesiones.log /home/retador/sesiones.log

RUN chown root:root portal.py tokens.json flag.txt \
    && chmod 600 tokens.json flag.txt \
    && chmod 755 portal.py \
    && chown retador:retador /home/retador/sesiones.log \
    && chmod 644 /home/retador/sesiones.log \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/portal.py *' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
