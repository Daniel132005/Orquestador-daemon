# Reto: SSRF por lista negra sensible a mayúsculas (OWASP A10:2021 -
# Server-Side Request Forgery). Dificultad: difícil.
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-ssrf:latest challenges/ssrf/

FROM ctf-base:latest

WORKDIR /app
USER root

COPY previsualizar.py flag.txt ./

RUN chown root:root previsualizar.py flag.txt \
    && chmod 600 flag.txt \
    && chmod 755 previsualizar.py \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/previsualizar.py *' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
