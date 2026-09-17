# Reto: pedidos sin control de acceso a nivel de objeto
# (OWASP A01:2021 - Broken Access Control / IDOR).
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-idor:latest challenges/idor/

FROM ctf-base:latest

WORKDIR /app
USER root

COPY pedidos.py pedidos.json ./

RUN chown root:root pedidos.py pedidos.json \
    && chmod 600 pedidos.json \
    && chmod 755 pedidos.py \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/pedidos.py *' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
