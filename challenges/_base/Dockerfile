# Base común de todos los retos (ver docs/dia-9-owasp-top-10-completo.md).
#
# Da el usuario sin privilegios que usa la consola y el mecanismo de
# escalar exactamente al comando de la app vulnerable, ni uno más. Sin
# esto, cualquier flag guardado en un archivo se lee con `cat` sin
# explotar nada — es lo que pasaba en los dos primeros retos.
#
# No se publica solo: cada reto hace `FROM ctf-base:latest`.
#
# Construir con:
#   docker build -t ctf-base:latest challenges/_base/

FROM alpine:latest

RUN apk add --no-cache bash python3 sudo \
    && adduser -D -s /bin/bash retador \
    && mkdir -p /etc/sudoers.d

CMD ["/bin/sh"]
