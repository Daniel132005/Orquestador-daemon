# Reto: cupón de descuento sin límite de usos (OWASP A04:2021 -
# Insecure Design). Dificultad: intermedio.
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-diseno-inseguro:latest challenges/diseno-inseguro/

FROM ctf-base:latest

WORKDIR /app
USER root

COPY tienda.py flag.txt ./

RUN chown root:root tienda.py flag.txt \
    && chmod 600 flag.txt \
    && chmod 755 tienda.py \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/tienda.py *' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
