# Reto: componente desactualizado con eval() sin sandbox (OWASP
# A06:2021 - Vulnerable and Outdated Components). Dificultad: intermedio.
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-componente-vulnerable:latest challenges/componente-vulnerable/

FROM ctf-base:latest

WORKDIR /app
USER root

COPY calculadora.py flag.txt ./

RUN chown root:root calculadora.py flag.txt \
    && chmod 600 flag.txt \
    && chmod 755 calculadora.py \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/calculadora.py *' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
