# Reto: credenciales con MD5 sin sal (OWASP A02:2021 - Cryptographic
# Failures). Dificultad: básico.
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/   (una sola vez)
#   docker build -t ctf-reto-crypto-debil:latest challenges/crypto-debil/

FROM ctf-base:latest

WORKDIR /app
USER root

COPY generar_hashes.py .
RUN python3 generar_hashes.py && rm generar_hashes.py
COPY login.py flag.txt ./
COPY wordlist.txt /home/retador/wordlist.txt

RUN chown root:root login.py flag.txt hashes.txt \
    && chmod 600 flag.txt hashes.txt \
    && chmod 755 login.py \
    && chown retador:retador /home/retador/wordlist.txt \
    && echo 'retador ALL=(root) NOPASSWD: /usr/bin/python3 /app/login.py *' > /etc/sudoers.d/reto \
    && chmod 440 /etc/sudoers.d/reto

USER retador
WORKDIR /home/retador
CMD ["/bin/sh"]
