# Reto: backup de configuración olvidado y legible por cualquiera
# (OWASP A05:2021 - Security Misconfiguration). Dificultad: básico.
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-misconfig:latest challenges/misconfig/

FROM ctf-base:latest

WORKDIR /app
USER root

COPY panel.py credenciales.json flag.txt ./
COPY config.yaml.bak /home/retador/config.yaml.bak

RUN chown root:root panel.py credenciales.json flag.txt \
    && chmod 600 credenciales.json flag.txt \
    && chmod 755 panel.py \
    && chown retador:retador /home/retador/config.yaml.bak \
    && chmod 644 /home/retador/config.yaml.bak \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/panel.py *' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
