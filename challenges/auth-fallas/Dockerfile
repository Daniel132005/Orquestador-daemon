# Reto: PIN de 4 dígitos sin límite de intentos (OWASP A07:2021 -
# Identification and Authentication Failures). Dificultad: intermedio.
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-auth-fallas:latest challenges/auth-fallas/

FROM ctf-base:latest

WORKDIR /app
USER root

COPY generar_pin.py .
RUN python3 generar_pin.py && rm generar_pin.py
COPY caja_fuerte.py flag.txt ./

RUN chown root:root caja_fuerte.py flag.txt pin.txt \
    && chmod 600 flag.txt pin.txt \
    && chmod 755 caja_fuerte.py \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/caja_fuerte.py *' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
