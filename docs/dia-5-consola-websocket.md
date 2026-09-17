# Día 5 — Puente WebSocket + Xterm.js

**Estado:** completado y verificado.
**Objetivo del plan:** consola interactiva real desde el navegador.
**Criterio de aceptación:** escribir un comando en la terminal del navegador y
ver la salida real del contenedor.

**Depende de:** [Día 4 — Destrucción automática](dia-4-destruccion-automatica.md).

> El plan marcaba este día como **el más delicado** de todo el proyecto, y
> recomendaba probar el `exec` aislado antes de conectarlo con Channels y el
> frontend. Se siguió esa recomendación: el hijack se validó por separado en el
> [Día 1](dia-1-api-docker-sin-sdk.md#5-verificación) antes de montar nada
> encima.

---

## 1. El recorrido de una tecla

```
navegador               servidor                      Docker
────────────────────────────────────────────────────────────────────
xterm.js
  │ onData("l")
  ▼
WebSocket ──frame binario──► TerminalConsumer.receive()
                                 │
                                 ▼
                             sock_sendall ──────► socket del exec
                                                        │
                                                        ▼
                                                   /bin/sh recibe "l"
                                                        │
xterm.write ◄──frame binario── _pump_docker_to_ws ◄─ sock_recv ◄─ eco
```

El consumer no interpreta nada: reenvía bytes crudos. Lo único que traduce es
el redimensionado del TTY.

---

## 2. Decisiones de diseño tomadas durante el día

### 2.1 Protocolo: binario para datos, texto para control

El SDD describe el WebSocket como un tubo de bytes puro. Hizo falta una
excepción: informar el tamaño de la terminal.

En vez de inventar una secuencia de escape (que podría aparecer en lo que
teclea un estudiante), se usa el tipo de frame del propio WebSocket:

| Frame | Significado |
|---|---|
| **Binario** | Tecleo del usuario, se reenvía tal cual al `exec` |
| **Texto (JSON)** | Mensaje de control. Hoy solo `{"type":"resize", ...}` |

La distinción es inequívoca y no requiere escapar nada.

### 2.2 El tamaño del TTY importa

Sin avisarle a Docker, el proceso del contenedor cree que la terminal mide
80×24 y cualquier programa de pantalla completa se dibuja mal. Se añadió
`resize_exec()` (`POST /exec/{id}/resize`), que el frontend invoca al conectar
y al redimensionar la ventana.

Verificado desde dentro del contenedor:

```console
/ # stty size
40 137          ← coincide con la ventana real, no con 24x80
```

### 2.3 Sin hilos por consola

La primera implementación leía el socket del `exec` con
`asyncio.to_thread(sock.recv, ...)`, lo que dejaba **un hilo bloqueado por cada
consola abierta**. Con un pool de 16 hilos, la plataforma se atascaba alrededor
de las 16 consolas y las conexiones caídas no liberaban su hilo nunca.

Se pasó a `loop.sock_recv()` / `loop.sock_sendall()` sobre el socket en modo no
bloqueante. El hallazgo, la medición comparada y el método de diagnóstico están
en la [guía de pruebas](guia-pruebas-manuales.md#e2--el-límite-de-consolas-simultáneas-hallazgo-y-corrección).

| | Antes | Después |
|---|---|---|
| Consolas simultáneas que funcionan | 0 / 20 | **20 / 20** |
| Estado de los hilos | `unix_stream_read_generic` | `futex_wait_queue` |

---

## 3. Verificación del criterio de aceptación

Prueba automatizada con un navegador real (Playwright), sobre la plataforma
completa:

```console
1) Sin instancia:            start habilitado, stop deshabilitado, terminal oculta
2) Con instancia desplegada: consola conectada, TTY 137x40
3) Recargar con instancia viva: reconecta sola
4) Comandos reales en la consola:
      / # id; stty size
      uid=0(root) gid=0(root) groups=0(root),...
      40 137
      / #
   OK  ejecuto id
   OK  el resize del TTY llegó al contenedor
5) Destruir: mensaje correcto, botones correctos, terminal oculta

TODO OK
```

**El criterio se cumple:** se escribe un comando en el navegador y se ve la
salida real del proceso dentro del contenedor.

---

## 4. Casos límite

Más allá del camino feliz, se probaron las cuatro situaciones en las que la
consola se corta sin que el usuario lo pida.

### 4.1 El estudiante escribe `exit`

Termina el `exec`, pero **no** el contenedor: la instancia sigue viva.

**Problema encontrado:** la interfaz decía solo "Consola desconectada", dejaba
la terminal muerta a la vista y no daba ninguna pista de que recargando se
recupera. Un estudiante quedaba mirando una pantalla inerte.

**Corregido:** ahora informa *"Consola cerrada — recargá para reabrirla"*, que
es exactamente lo que hay que hacer. Se verificó que al recargar se crea un
`exec` nuevo sobre el mismo contenedor y la consola vuelve a responder.

### 4.2 La instancia se destruye con la consola abierta

Es el final normal de cualquiera que se ausente 15 minutos, o sea justo lo que
produce el watchdog del Día 4.

**Problema encontrado, y era un bug:** la interfaz quedaba mintiendo. El panel
lateral seguía mostrando el contenedor destruido, y **el botón "Desplegar"
quedaba deshabilitado** — el estudiante no podía crear otra instancia sin
recargar la página.

**Corregido:** al cortarse la conexión de forma inesperada, el frontend vuelve
a consultar el estado al servidor y se resincroniza.

Un detalle de implementación que costó una iteración: la primera consulta
llegaba **demasiado pronto**. Al destruir una instancia, el contenedor muere
antes de que se borre su fila, así que el servidor todavía la reportaba activa.
Se resuelve reconsultando a los 3 segundos.

| | Antes | Después |
|---|---|---|
| Mensaje | "Consola desconectada" | "La instancia ya no existe" |
| Panel lateral | contenedor inexistente | limpio |
| Botón Desplegar | **deshabilitado** | habilitado |
| Terminal | visible y muerta | oculta |

### 4.3 Recargar con la instancia viva

Reconecta sola, creando un `exec` nuevo. Verificado también después de un
`exit`.

### 4.4 Abrir la consola sin instancia

El consumer cierra el WebSocket con código 4004 y la interfaz muestra "Sin
instancia" con el botón de desplegar habilitado. Correcto.

---

## 5. Lo que queda fuera

- **Reconexión automática** si se cae el WebSocket. El SDD la deja fuera de
  alcance (§8). Hoy el usuario recarga la página; la interfaz se lo indica
  explícitamente, que era el mínimo necesario para que no quede atrapado.
- **Historial de sesión.** Al recargar se abre un `exec` nuevo y la terminal
  arranca vacía: no se conserva lo que se había escrito antes.
- **Varios retos simultáneos por usuario.** El modelo es una instancia por
  usuario (SDD §7).
