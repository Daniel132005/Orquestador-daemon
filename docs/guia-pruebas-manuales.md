# Guía de pruebas manuales

Cómo reproducir a mano las 10 pruebas del Día 3, qué significa exactamente
cada resultado, y pruebas de estrés adicionales para encontrar los límites
reales de la plataforma.

---

## Preparativos

Vas a necesitar **tres ventanas** abiertas al mismo tiempo:

| Ventana | Qué es | Para qué |
|---|---|---|
| A | Navegador normal, sesión de `daniel` | El "atacante" |
| B | Navegador en **incógnito**, sesión de `estudiante` | El "testigo" |
| C | Terminal de Ubuntu (WSL) | Observar desde fuera |

> La ventana B **tiene que ser incógnito o un navegador distinto**. Si abrís
> dos pestañas normales compartirán la misma cookie de sesión y estarás
> logueado como el mismo usuario en ambas.

Usuarios de prueba: `daniel` / `123123` y `estudiante` / `123123`.

En las dos ventanas del navegador, apretá **Desplegar instancia** y esperá a
que el indicador diga "consola conectada".

---

## Cómo leer los números

Antes de las pruebas, conviene entender qué estás mirando.

### Los límites, vistos desde dentro del contenedor

Escribí esto en la consola del navegador:

```sh
cat /sys/fs/cgroup/memory.max     # 268435456
cat /sys/fs/cgroup/cpu.max        # 50000 100000
cat /sys/fs/cgroup/pids.max       # 64
```

| Valor | Qué significa |
|---|---|
| `268435456` | Bytes. Son 256 × 1024 × 1024 = **256 MB exactos** |
| `50000 100000` | "50000 microsegundos de CPU por cada 100000". O sea **50 % de un núcleo** |
| `64` | Máximo de procesos (PIDs) simultáneos |

Estos archivos los expone el **kernel**, no la aplicación. Si el número está
ahí, el límite está activo: no es una etiqueta decorativa.

### Los contadores de eventos

```sh
cat /sys/fs/cgroup/memory.events
```

```
low 0
high 0
max 280        ← cuántas veces se chocó contra el techo de memoria
oom 10         ← cuántas veces el kernel se quedó sin margen
oom_kill 1     ← cuántos procesos fueron EJECUTADOS por el kernel
```

`oom_kill` mayor que cero es la prueba definitiva de que el kernel intervino
matando algo. Si vale 0 pero `max` es alto, significa que contuvo frenando al
proceso en vez de matarlo (las dos cosas son contención válida).

### "Network unreachable" vs "timeout"

Es una distinción importante al leer las pruebas de red:

- **`Network unreachable`** — el kernel del contenedor no tiene ninguna ruta
  hacia ese destino, así que descarta el paquete sin enviarlo. Es un bloqueo
  estructural: no depende de un firewall que alguien podría desactivar.
- **`Connection refused`** — el paquete sí llegó, y del otro lado no hay nadie
  escuchando en ese puerto.
- **Timeout (se queda colgado)** — el paquete salió y nadie contestó. Suele
  indicar un firewall que descarta silenciosamente.

---

## Pruebas 1 y 2 — Dos usuarios, dos entornos

**En la ventana C:**

```bash
docker ps --format "{{.ID}}  {{.Image}}  {{.Status}}"
docker network ls --filter name=ctf-net --format "{{.Name}}"
```

**Esperado:** dos contenedores y dos redes con nombres distintos
(`ctf-net-1-...` y `ctf-net-2-...`; el número es el id del usuario).

Para ver la IP de cada uno:

```bash
docker inspect <ID_CONTENEDOR> --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
```

Anotá las dos IPs; las vas a necesitar. Serán parecidas a `172.22.0.2` y
`172.23.0.2` — **subredes distintas**, que es el punto.

---

## Prueba 3 — Un usuario no alcanza al otro

**En la consola del navegador A**, reemplazando por la IP del contenedor B:

```sh
ping -c 2 -W 2 172.23.0.2
nc -z -w 3 172.23.0.2 22
```

**Esperado:**

```
ping: sendto: Network unreachable
```

**Qué significa:** el contenedor de un estudiante no tiene forma de tocar el de
otro. El error aparece al instante, no después de esperar: el kernel ni
siquiera intentó enviar el paquete.

**Sería un fallo si:** ves respuestas de ping, o `nc` reporta el puerto
abierto.

---

## Prueba 4 — Escanear la propia red

**En la consola A:**

```sh
for i in $(seq 1 12); do ping -c1 -W1 172.22.0.$i >/dev/null 2>&1 && echo VIVO:172.22.0.$i; done
```

**Esperado:** exactamente dos respuestas: `172.22.0.1` (el host) y tu propia IP.

**Qué significa:** tu red no tiene más habitantes. Cada estudiante vive solo en
la suya.

---

## Prueba 5 — Sin salida a internet

**En la consola A:**

```sh
wget -T 4 -O- http://1.1.1.1
ping -c 2 -W 2 8.8.8.8
ip route
```

**Esperado:**

```
wget: can't connect to remote host (1.1.1.1): Network unreachable

172.22.0.0/16 dev eth0 scope link  src 172.22.0.2
```

**Qué significa, y este es el dato clave de todo el Día 3:** fijate que en
`ip route` **no hay una línea `default`**. Una red Docker normal agregaría
`default via 172.22.0.1`. Una red creada con `Internal: true` no lo hace.

Sin ruta por defecto, el contenedor solo puede hablar con su propia subred.
Ese renglón ausente es lo que hace que fallen las pruebas 3 y 5 — no hay
reglas de firewall involucradas, simplemente no existe el camino.

---

## Prueba 6 — Alcanzar el host

**En la consola A:**

```sh
ping -c 2 -W 2 172.22.0.1
wget -T 5 -O- http://172.22.0.1:8000/login/
```

**Esperado:** el ping **sí funciona** (el host es vecino en la red bridge), y
el wget da `Connection refused`.

**Cuidado con la interpretación.** El `Connection refused` aquí no prueba que
la plataforma esté protegida. En este entorno, Django corre en la distro
Ubuntu y el bridge de Docker vive en otro espacio de red, así que simplemente
no hay nada escuchando en esa dirección.

**En un servidor Linux real, donde Django y `dockerd` comparten host, un
estudiante sí podría alcanzar la plataforma desde su contenedor.** Es el punto
pendiente número uno de la sección de deuda del
[reporte del Día 3](dia-3-aislamiento-y-limites.md).

---

## Prueba 6b — Capacidades del contenedor

**En la consola A:**

```sh
grep CapEff /proc/self/status        # 0000000000000000
chown nobody /tmp                    # Operation not permitted
mknod /tmp/disco b 8 0               # Operation not permitted
ping -c1 127.0.0.1                   # sigue funcionando
```

**Esperado:** `CapEff` en ceros, las operaciones privilegiadas bloqueadas, y la
consola funcionando con normalidad.

**Qué significa:** el contenedor corre con `CapDrop: ["ALL"]`, sin ninguna
capacidad del kernel. Un proceso comprometido dentro del reto no puede cambiar
dueños de archivos, crear dispositivos ni montar filesystems.

**Dato contraintuitivo:** quitar todas las capacidades **no rompe `ping`**.
BusyBox usa sockets ICMP de datagrama, que no requieren `CAP_NET_RAW`.

**Lo que esto NO hace:** las capacidades **no aíslan la red**. Se comprobó
poniendo un contenedor con cero capacidades en la misma red que otro: lo
alcanzó por ping sin dificultad. El aislamiento entre estudiantes lo sostiene,
entero, la ausencia de ruta por defecto (prueba 5). Son dos capas
independientes y hacen falta las dos.

---

## Prueba 6c — Filesystem de solo lectura

**En la consola A:**

```sh
touch /probe              # Read-only file system
touch /etc/probe          # Read-only file system
touch /tmp/probe          # funciona
df -h /tmp                # 64.0M

printf '#!/bin/sh\necho hola\n' > /tmp/x.sh; chmod +x /tmp/x.sh
/tmp/x.sh                 # Permission denied  (noexec)
sh /tmp/x.sh              # hola               (el intérprete sí puede)
```

**Qué significa:** el contenedor corre con `ReadonlyRootfs`, así que un
estudiante no puede modificar el sistema de archivos del reto. Solo `/tmp` es
escribible, en memoria (tmpfs) y con tope de 64 MB.

**Matiz sobre `noexec`:** frena binarios depositados en `/tmp`, pero no
scripts — un intérprete puede leerlos igual. Tenelo en cuenta si diseñás un
reto que requiera compilar y ejecutar algo.

---

## Prueba 6d — Peticiones simultáneas del mismo usuario

Prueba de concurrencia, para confirmar que no se crean contenedores de más.
Desde la ventana C, con sesión iniciada, disparar varias peticiones a la vez:

```bash
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -w "%{http_code} " -X POST \
    -H "X-CSRFToken: $TOKEN" -H "Referer: http://localhost:8000/" \
    -b "sessionid=$SESION; csrftoken=$TOKEN" \
    http://localhost:8000/api/instance/start/ &
done; wait; echo

docker ps -q | wc -l                                  # debe ser 1
docker network ls --filter name=ctf-net -q | wc -l    # debe ser 1
```

**Esperado:** un `201` y el resto `409`, con **un solo** contenedor y una sola
red.

**Sería un fallo si:** aparecen códigos `500`, o si quedan más contenedores que
filas en la base — eso significa recursos huérfanos que nadie va a reclamar.

---

## Prueba 7 — Agotar la memoria

**En la consola A:**

```sh
cat /sys/fs/cgroup/memory.events     # anotá el valor de oom_kill ANTES

# lanzar 12 procesos de 40 MB cada uno = 480 MB pedidos, con 256 MB de límite
i=0; while [ $i -lt 12 ]; do (head -c 40000000 /dev/zero | tail -c 40000000 | sleep 300) & i=$((i+1)); sleep 1; echo "lanzados=$i uso=$(cat /sys/fs/cgroup/memory.current)"; done

cat /sys/fs/cgroup/memory.peak       # el dato decisivo
cat /sys/fs/cgroup/memory.events     # oom_kill DESPUÉS
```

**Esperado:**

```
memory.peak  = 268435456      ← exactamente el límite, ni un byte más
oom_kill     = 1 (o más)      ← el kernel mató procesos
```

Vas a ver un `Killed` en pantalla.

**Qué significa:** el contenedor **nunca** consiguió más memoria de la
asignada. Cuando insistió, el kernel eliminó procesos.

**Observación importante:** si en vez de este comando usás una tubería simple
(`head -c 400000000 /dev/zero | tail -c 399000000 | wc -c`), el proceso se
queda colgado en vez de morir, y `oom_kill` sigue en 0. **Eso no significa que
el límite falle**: mirá `docker stats` desde la ventana C y vas a ver el
contenedor clavado en 255 MiB / 256 MiB. El kernel está frenando al proceso en
lugar de matarlo, porque una tubería puede esperar indefinidamente. Las dos
cosas son contención válida.

**Para limpiar:** apretá "Destruir" y volvé a desplegar.

---

## Prueba 8 — Saturar la CPU

**En la consola A:**

```sh
for i in 1 2 3 4; do (while :; do :; done) & done
```

Eso lanza cuatro bucles infinitos: cuatro procesos intentando consumir cuatro
núcleos completos.

**En la ventana C, mientras corre:**

```bash
docker stats --no-stream --format "{{.Name}}  {{.CPUPerc}}  {{.MemUsage}}"
```

**Esperado:**

```
atacante   ~50%     ← topado, aunque pida 400%
testigo     0.00%
```

**Qué significa:** el porcentaje de `docker stats` es **relativo a un núcleo**.
50 % = medio núcleo = exactamente el `NanoCpus=500000000` configurado. Vas a
ver valores oscilando entre 49 % y 55 %: es ruido normal de muestreo, no una
fuga del límite.

**Comprobá al mismo tiempo** que la ventana B (el testigo) sigue respondiendo
normal y que la página de la plataforma carga rápido.

**Para frenar:** `kill %1 %2 %3 %4` o simplemente destruí la instancia.

---

## Prueba 9 — Fork bomb

**En la consola A:**

```sh
bomba() { bomba | bomba & }; bomba
```

**Esperado:** la consola se vuelve inutilizable y empieza a mostrar

```
sh: can't fork: Resource temporarily unavailable
```

**Qué significa:** `PidsLimit=64` se agotó. El error es `EAGAIN`, la forma en
que el kernel dice "no te doy más procesos". El ataque se contuvo solo.

**Lo importante es lo que NO pasa:** la ventana B sigue funcionando, la
plataforma sigue respondiendo, y tu PC no se cuelga. El que lanzó el ataque es
el único que lo sufre.

**Para limpiar:** apretá "Destruir" desde la interfaz. El contenedor se elimina
aunque esté saturado.

---

## Prueba 10 — Estado final

**Ventana C:**

```bash
docker ps
docker stats --no-stream
curl -o /dev/null -s -w "plataforma: HTTP %{http_code} en %{time_total}s\n" http://localhost:8000/login/
```

**Esperado:** la plataforma responde en decenas de milisegundos y el testigo
nunca registró incidentes:

```bash
docker exec <ID_TESTIGO> cat /sys/fs/cgroup/memory.events
# low 0 / high 0 / max 0 / oom 0 / oom_kill 0
```

---

# Pruebas de estrés: dónde está el cuello de botella real

Las 10 pruebas anteriores verifican el **aislamiento**. Estas buscan el
**límite de escala**: cuántos estudiantes soporta la plataforma antes de
romperse.

## E1 — Cuánto tarda crear una instancia

**Ventana C:**

```bash
time curl -s -o /dev/null -X POST http://localhost:8000/api/instance/start/ \
  -H "X-CSRFToken: ..." -b "sessionid=..."
```

**Medido en este proyecto:** ~0,87 s por instancia (mín. 0,77 s, máx. 1,01 s),
dominado por la creación de la red Docker.

**Implicación:** 30 estudiantes entrando a la vez tardan ~26 s en total, porque
las peticiones se serializan. No es fatal, pero el primero entra en 1 s y el
último espera casi medio minuto.

## E2 — El límite de consolas simultáneas (hallazgo y corrección)

> **Estado: corregido.** Esta sección documenta un cuello de botella grave que
> se encontró midiendo, y cómo se resolvió. Se conserva completa porque el
> método de diagnóstico sirve para detectar problemas parecidos.

**Cómo verlo, ventana C, con consolas abiertas:**

```bash
PID=$(ps -eo pid,cmd | grep 'bin/daphne' | grep -v grep | awk '{print $1}' | head -1)

# cuántos hilos tiene el servidor
ls /proc/$PID/task | wc -l

# en qué están bloqueados
for t in /proc/$PID/task/*; do
  echo "$(cat $t/comm) -> $(cat $t/wchan)"
done | grep asyncio

# cuántas consolas hay realmente conectadas
ss -tn state established '( sport = :8000 )' | tail -n +2 | wc -l
```

**Lo que se midió durante la prueba de carga con 20 consolas:**

```
16 asyncio_     ← el pool de hilos, en su tope máximo
WebSockets establecidos: 1
asyncio_0  -> unix_stream_read_generic
asyncio_1  -> unix_stream_read_generic
...
asyncio_15 -> unix_stream_read_generic
```

**Qué significa.** Cada consola abierta deja **un hilo del servidor bloqueado
permanentemente** esperando datos del contenedor (`unix_stream_read_generic` es
la función del kernel que espera en un socket Unix). Ese pool tiene un máximo
de `min(32, CPUs + 4)` hilos — en esta máquina, **16**.

Consecuencias:

1. **Techo duro de ~16 consolas simultáneas.** La 17ª se queda esperando un
   hilo que nunca se libera.
2. **Peor aún: los hilos se filtran.** En la medición había 16 hilos ocupados
   con **una sola consola viva**. Las conexiones que murieron sin cerrarse
   limpiamente dejaron su hilo bloqueado para siempre.
3. Cuando el pool se agota, `POST /api/instance/start/` **deja de responder**
   (se midió un timeout de 30 s), aunque `GET /login/` siga contestando en
   20 ms. El síntoma es confuso: "la web anda pero no puedo crear instancias".

### La corrección aplicada

Se dejó de usar un hilo por consola. El socket del `exec` ahora queda en modo
no bloqueante y lo atiende directamente el bucle de asyncio con
`loop.sock_recv()` y `loop.sock_sendall()`, sin intermediarios
([ctf/docker_client.py](../ctf/docker_client.py), clase `HijackedExecSocket`).

Eso arregla dos cosas a la vez:

1. **No se consume un hilo por consola**, así que desaparece el techo de 16.
2. **La cancelación pasa a ser inmediata.** Antes, cancelar la tarea lectora no
   interrumpía a un hilo ya bloqueado dentro de `recv()`; por eso al destruir
   una instancia o caerse una conexión el hilo quedaba colgado para siempre.
   Sin hilo de por medio, `task.cancel()` surte efecto al instante, y
   `disconnect()` ahora cancela y espera **antes** de cerrar el socket.

### Medición antes y después

Misma prueba: 20 usuarios abriendo consola a la vez y ejecutando un comando.

| Medición | Antes | Después |
|---|---|---|
| Consolas que ejecutaron el comando | 0 / 20 | **20 / 20** |
| Hilos del servidor | 16 (tope del pool) | 14 |
| Estado de esos hilos | `unix_stream_read_generic` (bloqueados en E/S) | `futex_wait_queue` (ociosos) |
| WebSockets vivos con el pool lleno | 1 | 20 |
| Sockets a Docker sin consolas abiertas | 25 (filtrados) | 3 |
| `POST /api/instance/start/` | timeout a los 30 s | 14 ms |

El dato que cierra el caso es el **estado de los hilos**:
`unix_stream_read_generic` significa "bloqueado esperando datos de un socket";
`futex_wait_queue` significa "ocioso, esperando trabajo". Los 14 hilos que
quedan no crecen con el número de consolas: son del pool que atiende las
llamadas cortas (crear el `exec`, redimensionar el TTY) y se reutilizan.

### Cómo comprobarlo vos mismo

Con varias consolas abiertas, en la ventana C:

```bash
PID=$(ps -eo pid,cmd | grep 'bin/daphne' | grep -v grep | awk '{print $1}' | head -1)
for t in /proc/$PID/task/*; do
  echo "$(cat $t/comm) -> $(cat $t/wchan)"
done | grep asyncio
```

Si ves `futex_wait_queue`, los hilos están libres. Si vieras
`unix_stream_read_generic` en muchos de ellos, habría vuelto el problema.

## E2b — Fuga de procesos al reconectar

Cada conexión de consola crea un `exec` en el contenedor. Si al desconectar no
se matara su shell, los procesos se acumularían contra el `PidsLimit` de 64.

**Cómo comprobarlo:** con una instancia desplegada, recargá la página del
navegador unas 10 veces seguidas. Después, en la ventana C:

```bash
CID=$(docker ps -q | head -1)
docker exec $CID cat /sys/fs/cgroup/pids.current
docker exec $CID ps -o pid,stat,args
```

**Esperado:** `pids.current` se mantiene estable (2 o 3), y en `ps` aparece un
solo `/bin/sh` además del proceso principal.

**Sería un fallo si:** el número crece con cada recarga. Eso significaría que
tras unas 55 recargas el estudiante se quedaría sin poder ejecutar nada en su
propio contenedor. Fue un bug real, corregido matando el shell del `exec` al
desconectar (ver [Día 5 §5.4](dia-5-consola-websocket.md)).

---

## E3 — Contención de SQLite

Cada tecla que escribe un estudiante hace un `UPDATE` de `last_activity`.
SQLite bloquea **toda la base** en cada escritura.

**Cómo observarlo:** con varias consolas abiertas, escribir rápido en todas y
vigilar si aparecen errores `database is locked` en el log del servidor.

**Implicación:** con un curso entero tecleando, SQLite se vuelve el siguiente
cuello de botella después de los hilos. La solución es PostgreSQL, y está
anticipada como trade-off en la sección 7 del SDD.

## E4 — Sin límite global de instancias

```bash
docker ps -q | wc -l        # crece sin tope
```

Nada impide que N usuarios levanten N contenedores hasta agotar la memoria del
host. **Cada contenedor está limitado a 256 MB, pero el total no está limitado
a nada.** Con 7,6 GB de RAM en la VM, unos 30 contenedores activos usando su
cuota completa saturarían la máquina.

Está declarado fuera de alcance en la sección 8 del SDD, pero es el primer
límite que conviene agregar antes de usar la plataforma con un curso real.

---

## Resumen: qué está sólido y qué no

| Aspecto | Estado |
|---|---|
| Aislamiento de red entre estudiantes | **Sólido**, verificado atacándolo |
| Límites de memoria, CPU y procesos | **Sólidos**, verificados atacándolos |
| Socket de Docker fuera del contenedor | **Correcto** |
| Capacidades del contenedor | **`cap-drop ALL` aplicado**, sin costo funcional |
| Escala de consolas simultáneas | **Corregido** — 20/20 verificadas, sin consumo de hilos por consola |
| Procesos al reconectar | **Corregido** — 0 fugas en 25 reconexiones (antes 1 por cada una) |
| Inundación de salida de un estudiante | **No afecta a los demás** — 17 MB/s sin degradar al resto |
| Pegado de texto | Íntegro hasta 1 MB. Se **ejecuta** al pegar: falta `bracketed paste` (ver Día 5 §5.5) |
| Base de datos bajo concurrencia | **Frágil** — SQLite serializa escrituras |
| Límite global de recursos | **Ausente** |
| Endurecimiento del contenedor | **Parcial** — `cap-drop ALL` y FS de solo lectura aplicados; falta no correr como root |

Lo que el MVP prometía —aislar a los estudiantes entre sí y del host— está
cumplido y demostrado. Lo que falta es lo que hace falta para pasar de una demo
a un aula.
