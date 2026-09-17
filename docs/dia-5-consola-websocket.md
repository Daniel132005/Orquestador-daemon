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

## 5. Pruebas de estrés

Los casos límite miden qué pasa cuando la consola se corta. Estas miden qué
pasa cuando **un estudiante abusa de ella**, y sobre todo si eso afecta a los
demás.

### 5.1 Inundación de salida — sin impacto

Un estudiante ejecuta `cat /dev/urandom`: el contenedor vuelca **17 MB/s** por
el WebSocket durante 15 segundos.

| Métrica | Base | Durante la inundación |
|---|---|---|
| Memoria del servidor | 742,4 MB | **742,4 MB** (sin cambio) |
| Latencia HTTP | 13 ms | 28–41 ms |
| **Consola de otro estudiante** | 14 ms | **5–8 ms** |

La preocupación de partida era que `daphne` usa un único bucle de eventos y un
estudiante inundando podría dejar sin CPU al resto. **No ocurre:** reenviar
bytes es lo bastante barato como para no competir con nada. El testigo ni se
enteró.

Conviene notar que los límites de cgroups **no** protegen de esto: topan la CPU
*dentro* del contenedor, pero el trabajo de reenviar esos bytes lo hace el
servidor, que no tiene límite. El resultado es bueno por eficiencia, no por
contención.

### 5.2 Lector lento — la memoria queda acotada

Mismo escenario, pero el cliente deja de leer. La memoria del servidor creció
**+21 MB y se detuvo**: hay contrapresión real, no se encola sin límite. La
plataforma siguió respondiendo entre 11 y 37 ms.

### 5.3 Pegado masivo — íntegro, pero costó medirlo bien

Al pegar texto, xterm.js no manda tecla por tecla: dispara un solo evento con
todo el contenido, que viaja como **un único frame binario**. La pregunta es si
ese volumen llega completo al proceso del contenedor.

Importa porque una terminal tiene un búfer de entrada limitado, y es la razón
por la que pegar texto largo en una terminal a veces corta líneas.

Medición, escribiendo lo pegado a un archivo con un heredoc y contándolo
**desde fuera** con `docker exec`:

| Enviado | Líneas | Llegado | Resultado |
|---|---|---|---|
| 4.096 B | 64 | 4.097 B | Íntegro |
| 65.536 B | 1.024 | 65.537 B | Íntegro |
| 131.072 B | 2.048 | 131.073 B | Íntegro |
| 524.288 B | 8.192 | 524.289 B | Íntegro |
| **1.048.576 B** | **16.384** | 1.048.577 B | **Íntegro** |

(el byte extra es el salto de línea que cierra el heredoc)

Sin pérdida en ningún tamaño, hasta 1 MB. Para efectos prácticos **no hay
límite de transporte**: nadie pega un millón de caracteres a mano.

**Dos intentos fallidos antes de llegar acá, que vale documentar porque el
método de medición cambió la conclusión:**

1. La primera versión solo comprobaba que no hubiera excepción. Eso no prueba
   que los datos lleguen: la plataforma puede no romperse y aun así perder la
   mitad del pegado.
2. La segunda **sí midió, y reportó 87 % de pérdida** — pero era un artefacto.
   El cliente de prueba no leía la salida mientras pegaba. El shell hace eco de
   todo lo que recibe; si nadie consume ese eco, su búfer de salida se llena,
   el shell se bloquea escribiendo y deja de leer la entrada. Ahí sí se pierden
   datos.

Un navegador real siempre consume la salida, porque la dibuja en pantalla. Al
añadir ese consumo a la prueba, la pérdida desapareció.

**Conclusión:** los pegados llegan completos con cualquier cliente que lea la
salida, que es el caso de la interfaz real.

### 5.5 Lo pegado se ejecuta: falta `bracketed paste`

Cuánto llega es una pregunta; qué hace el shell con lo que llega es otra, y
esta última tiene una consecuencia práctica.

Se pegaron tres líneas, cada una un comando `touch`:

```console
archivos creados: 3 de 3
```

**Pegar es idéntico a teclear**: cada línea terminada en salto se ejecuta al
instante, sin confirmación. Eso es así en toda terminal y no es particular de
esta plataforma.

Pero hay una diferencia con una terminal de escritorio corriente. `bash` y
`zsh` implementan **bracketed paste**: el shell reconoce que el texto viene de
un pegado y **no lo ejecuta** hasta que la persona pulsa Enter, dándole ocasión
de revisarlo. **BusyBox `ash`, que es el shell de Alpine, no lo implementa** —
se verificó que el contenedor solo tiene `ash`, sin readline.

Consecuencias:

- Un estudiante que pega por error un script de 100 líneas ejecuta 100
  comandos de inmediato.
- Habilita el *pastejacking*: una página maliciosa puede dejar en el
  portapapeles un comando oculto con un salto de línea final, que se ejecuta
  solo al pegarlo. En una plataforma donde los estudiantes copian fragmentos de
  enunciados y de internet, no es un escenario rebuscado.

**Gravedad real: baja**, y por lo que ya se verificó en el
[Día 3](dia-3-aislamiento-y-limites.md). El peor caso es que el estudiante
destroce su propio contenedor aislado, donde ya es root, sin salida a internet
y sin alcance hacia los demás; el watchdog lo recicla a los 15 minutos. El
aislamiento es justamente lo que acota este riesgo.

### 5.6 `bracketed paste`: implementado y activo

`bracketed paste` no lo decide la terminal por su cuenta: es un **acuerdo entre
el shell y la terminal**. El shell anuncia que entiende marcadores de pegado
emitiendo `\x1b[?2004h`, y recién entonces la terminal envuelve lo pegado entre
`\x1b[200~` y `\x1b[201~`, para que el shell lo inserte sin ejecutarlo.

Comprobación de qué anuncia cada shell al arrancar, por el mismo camino que usa
la plataforma:

```console
/bin/sh    →  b'/ # \x1b[6n'                    ← no lo anuncia
/bin/bash  →  b'\x1b[?2004h9cbe9319a661:/# '    ← lo anuncia (activo por defecto)
```

xterm.js ya implementa su mitad del acuerdo, así que bastaba con cambiar el
shell. **Queda implementado y activo por defecto**, con dos piezas:

**1. La imagen del reto incluye `bash`** ([`challenge/Dockerfile`](../challenge/Dockerfile)):

```dockerfile
FROM alpine:latest
RUN apk add --no-cache bash
```

Cuesta 3 MB: la imagen pasa de 12,9 MB a 16,2 MB.

**2. La consola elige el shell sola.** No hay que configurar nada: el comando
del `exec` comprueba dentro del contenedor si existe `bash` y lo usa; si no,
cae a `sh` como antes.

```sh
if command -v bash >/dev/null 2>&1; then exec bash; else exec /bin/sh; fi
```

La detección ocurre dentro del contenedor, así que funciona con cualquier
imagen que traiga un profesor, sin que tenga que saber de esto.
`CTF_CONSOLE_SHELL` permite forzar uno concreto si hiciera falta.

**Verificación de punta a punta**, pegando tres comandos en un navegador real
y con la configuración por defecto, sin variables de entorno:

```console
archivos creados SIN pulsar Enter:  0 de 3   ← nada se ejecutó solo
la terminal muestra las 3 líneas esperando
archivos creados TRAS pulsar Enter: 3 de 3   ← recién ahí corren
```

El estudiante ve lo que va a ejecutar antes de que ocurra, que es exactamente
la protección que faltaba.

**Verificación del respaldo:** con `alpine:latest` puro, sin `bash`, la consola
sigue funcionando con `sh` y todas las pruebas pasan. La mejora no rompe las
imágenes que no lo traigan.

**Lo que esto no cubre:** si el texto pegado contiene un `\r` en vez de `\n`,
o secuencias de escape que manipulen la terminal, hay técnicas más elaboradas
que siguen siendo posibles. `bracketed paste` eleva bastante el listón, no lo
vuelve imposible.

### 5.7 Ctrl+V tuvo que implementarse a mano

Al probarlo en el navegador apareció que **Ctrl+V no pegaba nada**. La primera
pista fue lo que quedaba escrito en la terminal:

```console
0cca2adfba00:/# ^[[200~echo hola~
```

Los marcadores de bracketed paste aparecían como texto literal. La causa no es
un fallo: **en una terminal, Ctrl+V significa otra cosa**. Es `quoted-insert`
de readline, "insertá el siguiente carácter sin interpretarlo", así que se
comía el marcador de apertura del pegado.

O sea que el comportamiento era correcto para una terminal, pero no el que
espera quien usa un navegador. Se interceptan Ctrl+V y Ctrl+Shift+V en el
frontend y se resuelven con `term.paste()`, que respeta el modo bracketed
paste:

```js
term.attachCustomKeyEventHandler((evento) => {
  const esPegar = evento.type === "keydown" &&
    (evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === "v";
  if (!esPegar) return true;
  navigator.clipboard.readText().then((t) => t && term.paste(t));
  return false;   // no reenviar la tecla al shell
});
```

**Costo asumido:** se pierde `quoted-insert`, que en una terminal sirve para
escribir caracteres de control a mano. Para una consola en el navegador, poder
pegar vale bastante más que esa función.

Verificado: el texto aparece limpio, sin marcadores, y un pegado de varias
líneas sigue esperando a que la persona pulse Enter.

### 5.4 Fuga de procesos al reconectar — **bug encontrado y corregido**

Esta prueba sí encontró un problema serio. Veinticinco ciclos de conectar y
desconectar:

```console
antes:           pids.current=8
tras  5 ciclos:  pids.current=13   (+5)
tras 25 ciclos:  pids.current=33   (+25)
```

**Exactamente un proceso por reconexión**, es decir, por cada recarga de
página. Y no eran zombis que el sistema fuera a recoger, sino `/bin/sh` vivos
en estado `S`, durmiendo sobre una terminal que nadie iba a leer.

Es comportamiento conocido de Docker: al cortarse la conexión de un `exec`, el
proceso **no** muere. Con el `PidsLimit` de 64, tras unas 55 recargas el
estudiante se quedaba sin poder ejecutar nada dentro de su propio reto, sin
ninguna pista de por qué.

**Corrección.** El shell de la consola ahora deja su PID en un archivo de
`/tmp` antes de convertirse en shell interactivo, y al desconectar se lanza un
`exec` breve que lo mata.

Un detalle costó una iteración: la primera versión usaba `kill` a secas y **no
surtía ningún efecto**. La pista fue que los archivos de PID sí desaparecían
—o sea que la limpieza se ejecutaba— pero los procesos seguían vivos. La causa
es que **un shell interactivo ignora SIGTERM** a propósito: es justamente lo
que impide que Ctrl-C lo mate. Se pasó a `SIGKILL` sobre el grupo de procesos,
para no dejar huérfanos los trabajos en segundo plano.

```console
Después: +0 procesos tras 25 reconexiones   (antes +25)
consola tras 25 ciclos: responde
```

---

## 6. Lo que queda fuera

- **Reconexión automática** si se cae el WebSocket. El SDD la deja fuera de
  alcance (§8). Hoy el usuario recarga la página; la interfaz se lo indica
  explícitamente, que era el mínimo necesario para que no quede atrapado.

  Antes de implementarla conviene tener presente que **reconectar no es
  reanudar**: cada conexión crea un `exec` nuevo, o sea un shell nuevo. El
  estudiante recuperaría la consola, pero perdería su directorio de trabajo,
  sus variables, su historial y cualquier proceso en primer plano. Una
  reconexión silenciosa que devuelve un shell vacío puede confundir más que un
  mensaje claro de desconexión.

  Para que reconectar signifique *reanudar* hay dos caminos:

  1. Correr la consola dentro de `tmux` o `screen` en el contenedor y que cada
     conexión se enganche a la misma sesión. Requiere incluirlo en la imagen
     del reto.
  2. Atacar el proceso principal del contenedor con
     `POST /containers/{id}/attach` en vez de crear `exec`. Ese sí admite
     reengancharse, y de paso elimina por completo la fuga de procesos (§5.4),
     porque deja de crearse un shell por conexión. El costo: si el estudiante
     escribe `exit`, muere el proceso principal y con él el contenedor entero.
- **Historial de sesión.** Al recargar se abre un `exec` nuevo y la terminal
  arranca vacía: no se conserva lo que se había escrito antes.
- **Varios retos simultáneos por usuario.** El modelo es una instancia por
  usuario (SDD §7).
