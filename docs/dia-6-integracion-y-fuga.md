# Día 6 — Pruebas de integración y de fuga

**Estado:** completado.
**Objetivo del plan:** confirmar que lo construido realmente aísla y limita,
no solo que "funciona en el camino feliz".
**Criterio de aceptación:** los intentos de romper el aislamiento fallan como
se espera, y el sistema sigue respondiendo bajo carga básica.

**Depende de:** [Día 5 — Consola WebSocket](dia-5-consola-websocket.md).

---

## 1. Qué de este día ya estaba cubierto

Dos de las tres tareas del plan ya se habían verificado, y con más margen del
que pedía:

| Tarea del plan | Dónde se cubrió | Margen |
|---|---|---|
| Simular 2-3 usuarios conectados a la vez | [Día 3](dia-3-aislamiento-y-limites.md) (2 usuarios) y [Día 5 §E2](guia-pruebas-manuales.md) (20 consolas) | 6-10× lo pedido |
| Romper el aislamiento de red a propósito | [Día 3](dia-3-aislamiento-y-limites.md), 10 pruebas adversariales | Completo |

Lo que faltaba era la tercera: **límites de recursos y watchdog actuando
juntos**, no cada uno por separado. El Día 3 probó los límites solos; el Día 4
probó el watchdog solo (por inactividad). Nunca se comprobó qué pasa cuando
ambos mecanismos se cruzan — que es exactamente donde vive un caso real: un
estudiante que lanza algo pesado y se va.

---

## 2. Prueba 1 — Bucle infinito silencioso + abandono

**Hipótesis:** si un estudiante lanza un proceso que consume CPU pero no
produce salida, y deja de interactuar, el watchdog debería reciclarlo igual,
sin que el consumo de CPU se lo impida.

Umbral configurado para la prueba: 40 s de inactividad, barrido cada 15 s.

```console
lanzando: while true; do :; done &
CPU del contenedor tras lanzarlo: 49.40%

t+ 5s   instancia_activa=True   contenedor_vivo=True
t+25s   instancia_activa=True   contenedor_vivo=True
t+56s   instancia_activa=True   contenedor_vivo=True
t+61s   instancia_activa=False  contenedor_vivo=False

>>> DESTRUIDA a los 61s, pese al bucle activo
```

**Confirmado.** El límite de CPU contuvo el bucle en ~50 % de un núcleo
mientras corría, y el watchdog lo destruyó una vez superado el umbral de
inactividad — el consumo de recursos no interfiere con la destrucción. Los dos
mecanismos operan en capas independientes: uno limita cuánto puede usar un
contenedor, el otro decide cuándo debe dejar de existir.

---

## 3. Prueba 2 — Bucle infinito con salida periódica + abandono

**Hipótesis, ya anotada como riesgo en el [Día 4](dia-4-destruccion-automatica.md#1-cómo-funciona)
sin datos que la respaldaran:** si el bucle sí produce salida, esa salida
sigue refrescando `last_activity`, y la instancia nunca se destruye mientras
el WebSocket permanezca conectado — aunque el estudiante ya no esté mirando la
pantalla.

```console
lanzando: while true; do date; sleep 3; done &

t+10s   instancia_activa=True  contenedor_vivo=True
t+40s   instancia_activa=True  contenedor_vivo=True
t+81s   instancia_activa=True  contenedor_vivo=True

>>> SIGUE VIVA tras 75s (> umbral de 40s)
```

**Confirmado con evidencia real.** La instancia sobrevivió más del doble del
umbral configurado. Esto no es un fallo del watchdog: está haciendo
exactamente lo que se le pidió, actualizar `last_activity` cuando hay
actividad observable. El problema es de diseño — "actividad" incluye la salida
del proceso, no solo el estudiante presente.

**Deuda que esto convierte de teórica en medida:** la "vida máxima absoluta"
mencionada en el Día 4 sigue pendiente. Sin ella, cualquier estudiante puede
mantener su instancia viva para siempre con un bucle tan simple como el de
arriba, sin ninguna interacción de su parte.

---

## 4. Prueba 3 — Tres usuarios abusando de recursos a la vez

Las pruebas anteriores del proyecto usaban un atacante y, como mucho, un
testigo pasivo. Esta prueba lanza **tres ataques distintos y simultáneos**:

| Usuario | Ataque |
|---|---|
| `daniel` | 4 bucles de CPU (saturando su cuota de 0,5 núcleo) |
| `estudiante` | Reserva de memoria muy por encima del límite de 256 MB |
| `atacante3` | Fork bomb |

```console
Latencia HTTP ANTES del ataque: 20 ms

Lanzando los 3 ataques EN PARALELO...

t+ 3s  latencia HTTP:  10 ms   CPU(daniel)=49.97%
t+ 6s  latencia HTTP:  10 ms   CPU(daniel)=49.15%
t+ 9s  latencia HTTP:  13 ms   CPU(daniel)=52.54%
t+12s  latencia HTTP:   8 ms   CPU(daniel)=49.75%

Latencia HTTP DESPUES (los 3 ataques todavia corriendo): 29 ms
```

**Confirmado.** El host no se degradó de forma perceptible con tres ataques
simultáneos corriendo (8-29 ms contra 20 ms en reposo). Cada límite de CPU
siguió sosteniendo su cuota individual sin verse afectado por los otros dos
ataques en paralelo.

---

## 5. Lo que salió distinto a lo esperado, e investigado hasta el fondo

Dos mediciones de esta prueba no coincidían con lo documentado en el Día 3, y
se investigaron antes de aceptarlas.

### 5.1 `oom_kill=0` en el ataque de memoria — no es una discrepancia

La primera corrida de la prueba 3 dio `oom_kill=0` para el ataque de memoria,
lo que a primera vista contradice el Día 3. Al repetirlo con el mismo patrón
progresivo de esa prueba original:

```console
eventos de memoria tras el ataque:
  low 0  high 0  max 282  oom 0  oom_kill 0  oom_group_kill 0
pico de memoria: 268435456
```

**No es una discrepancia: es el otro modo de contención que ya describe el
Día 3 §9.1.** El pico de memoria es `268435456` — exactamente 256 MB, ni un
byte más — y `max=282` muestra que se chocó contra el techo 282 veces. El
límite contuvo por **estancamiento** en vez de por muerte, que es el
comportamiento esperado cuando la memoria se pide con tuberías en vez de con
asignación anónima directa. El resultado depende de cómo el estudiante pida la
memoria, no de una falla del límite.

### 5.2 El fork bomb: contenido, pero con un matiz sobre qué comandos pasan

La medición inicial de la prueba 3 mostró que el contenedor **aceptaba
comandos nuevos** durante el fork bomb — lo opuesto a lo que documentó el Día
3 (`can't fork: Resource temporarily unavailable`). Se investigó en tres
pasos.

**Paso 1 — el comando de prueba importaba.** El primer chequeo usaba `echo`,
que es una función interna del shell y no necesita hacer `fork()`. Repitiendo
con un binario externo (`/bin/ls`), en el mismo instante del ataque:

```console
A) comando BUILTIN (echo):    rc=0  (pasa)
B) comando EXTERNO (/bin/ls): rc=2  sh: can't fork: Resource temporarily unavailable
C) 5 reintentos del externo:  0/5 exitosos
```

Confirmado: el límite de PIDs sí bloquea la creación de procesos nuevos,
exactamente como en el Día 3. `echo` pasaba porque nunca necesitó pedirle un
PID nuevo al kernel.

**Paso 2 — `pids.current` mostró 65 con un límite de 64.** Parecía que el
cgroup permitía superar su propio techo. La explicación: **medir con
`docker exec` agrega un proceso más**, transitoriamente, mientras ese comando
de medición corre dentro del mismo cgroup. El valor en reposo es 64 — al
límite, no por encima.

**Paso 3 — si un comando externo se reintenta varias veces, a veces pasa.**
Una fork bomb con `bomba() { bomba | bomba & }` no mantiene 64 procesos fijos:
es un *churn* de procesos que nacen, se bifurcan y mueren muy rápido. La
ocupación real fluctúa pegada al techo, así que a veces se libera un lugar por
una fracción de segundo justo cuando algo externo intenta forkear. Es
comportamiento esperado de cómo funciona un fork bomb, no una falla de
contención — el promedio observado en repeticiones sigue siendo "casi siempre
bloqueado, ocasionalmente pasa por una rendija".

**El punto que sí importaba verificar:** ¿esa saturación le impide a la
plataforma destruir la instancia? Se probó lanzando el fork bomb sin límite de
tiempo y pidiéndole a la API que la detenga mientras seguía corriendo:

```console
pids.current mientras esta saturado: 65

POST /instance/stop/  ->  HTTP 200  en 5502 ms
{"status": "detenida"}

¿el contenedor sigue vivo tras destruir?  NO -- destruido correctamente
```

**Funciona siempre, sin depender de la suerte del fork bomb.** La razón es
estructural: `destroy_instance()` detiene y borra el contenedor por la API de
Docker desde **fuera** (`POST .../stop`, `DELETE ...`), no ejecutando un
comando *dentro* del contenedor. No necesita un PID libre en el cgroup
saturado, así que la saturación de un estudiante nunca puede impedir que su
propia instancia se recicle.

---

## 6. Resumen

| Escenario | Resultado |
|---|---|
| Bucle de CPU silencioso + abandono | **Watchdog recicla igual** (61s), límite de CPU sostenido mientras corrió |
| Bucle con salida periódica + abandono | **Sigue vivo indefinidamente** (>75s) — deuda conocida, ahora medida |
| 3 ataques simultáneos (CPU/memoria/PIDs) | **Host sin degradación** (8-29 ms vs. 20 ms en reposo) |
| Destruir una instancia saturada por fork bomb | **Siempre funciona** — la destrucción no pasa por el cgroup saturado |

El criterio de aceptación del plan se cumple: los intentos de romper el
aislamiento fallan como se espera, y el sistema sigue respondiendo bajo carga.

La deuda que queda, y que esta ronda de pruebas convirtió de sospecha en
hecho medido, es la vida máxima absoluta de una instancia (§3). Las demás
piezas —aislamiento de red, límites de recursos, watchdog, resiliencia de la
destrucción— se sostienen incluso combinadas y bajo ataque simultáneo.
