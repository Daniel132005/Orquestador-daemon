# Imagen base para los retos.
#
# Construir con:
#   docker build -t ctf-challenge:latest challenge/
#
# `bash` no está por comodidad: es lo que activa `bracketed paste`, la
# protección que impide que un texto pegado en la consola se ejecute solo
# línea por línea (ver docs/dia-5-consola-websocket.md §5.5). BusyBox `ash`,
# el shell por defecto de Alpine, no lo soporta.
#
# Cuesta 3 MB: la imagen pasa de 12,9 MB a 16,2 MB.

FROM alpine:latest

RUN apk add --no-cache bash

# El contenedor debe quedarse vivo esperando: la consola del estudiante no
# usa este proceso, sino un `exec` aparte.
CMD ["/bin/sh"]
