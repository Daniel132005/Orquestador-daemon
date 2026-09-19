# Arquitectura del Sistema — Plataforma CTF con Contenedores Dinámicos

> Documento de referencia técnica: qué se construyó, por qué se decidió así, cómo funcionan y se conectan las piezas (frontend, backend, WebSocket, watchdog) y qué tan lejos escala hoy en lo operativo y económico.
> Complementa a [docs/arquitectura.md](docs/arquitectura.md) (diagrama y justificación por decisión) y a `docs/sdd-plataforma-ctf.md` (Software Design Document). Este documento añade la lectura de extremo a extremo y el análisis de escalabilidad/costo que faltaba.

---

## 1. Qué es el sistema

Una plataforma educativa de retos de ciberseguridad (CTF, estilo OWASP Top 10) donde cada estudiante autenticado despliega **su propio contenedor Docker aislado** bajo demanda, interactúa con él por una **terminal web en tiempo real** (Xterm.js sobre WebSocket), y el sistema **destruye automáticamente** ese entorno cuando expira por inactividad o por tiempo máximo de vida.

Es una única aplicación **Django** (no microservicios): un mismo proceso sirve HTTP, WebSocket y corre el proceso de limpieza (watchdog) en un hilo interno.

---

## 2. Por qué se decidió esta arquitectura

El proyecto parte de tres restricciones de diseño explícitas (documentadas en `docs/arquitectura.md` y `docs/sdd-plataforma-ctf.md`), y cada decisión de stack responde a una de ellas:

| Restricción / necesidad | Decisión tomada | Alternativa descartada y por qué |
|---|---|---|
| Orquestar Docker sin SDK de alto nivel | Cliente propio (`ctf/docker_client.py`) hablando HTTP directo contra `/var/run/docker.sock` vía `requests-unixsocket` | `docker-py` (viola la restricción) o `subprocess.Popen(["docker", ...])` (un proceso hijo por acción, fugas de descriptores y señales difíciles de gestionar) |
| Terminal interactiva en el navegador | Xterm.js + WebSocket binario + "hijacking" manual del exec de Docker (`Upgrade: tcp`, socket crudo `AF_UNIX`) | Polling HTTP (alta latencia, no apto para TTY) |
| Cientos de conexiones WebSocket de larga duración (minutos/horas) sin tumbar el servidor | Django Channels 4 + Daphne (ASGI, asíncrono) | Django clásico con WSGI síncrono (Gunicorn/uWSGI): cada consola abierta bloquea un worker completo; con ~10 estudiantes conectados el pool de workers se agota |
| Impedir que un contenedor ataque a otro estudiante o salga a Internet | Red Docker *bridge* dedicada por usuario con `"Internal": true` (sin ruta por defecto) | `iptables`/`nftables` manuales: frágil, requiere root en el orquestador, se desincroniza en reinicios |
| Impedir fork-bombs / consumo desbocado de RAM-CPU | Límites declarados en `HostConfig` (`Memory`, `NanoCpus`, `PidsLimit`) resueltos por **cgroups del kernel** | Un script en Python vigilando uso de recursos: llega tarde, el host ya sufrió el pico antes de reaccionar |
| Contenedores huérfanos si el servidor se reinicia o el estudiante cierra el navegador | Estado persistido en base de datos (`Instance.last_activity`) + barrido periódico independiente (watchdog) | `threading.Timer` en memoria: desaparece con cualquier reinicio del proceso, deja contenedores corriendo indefinidamente |
| Terminar el proceso del exec al desconectar (Docker no lo hace solo, y un shell ignora SIGTERM) | Guardar el PID del shell y matarlo con `kill -9` al cerrar el WebSocket (`terminate_console`) | Dejarlo vivo: acumula procesos zombis contra el `PidsLimit` del contenedor |
| Cambiar umbrales del watchdog sin reiniciar el servidor | Modelo singleton `PlatformSettings` en base de datos, editable desde `/admin/` o desde un panel oculto en el propio frontend | Variables de entorno fijas: cualquier cambio exige reiniciar el proceso Daphne |

**Resultado de estas decisiones:** todo el aislamiento fuerte (red, CPU, memoria, procesos) lo hace el **kernel de Linux vía Docker**, no código de aplicación — es la parte más robusta del sistema. La parte más frágil, en cambio, es todo lo que asume "un solo proceso" (ver sección 6).

---

## 3. Componentes y cómo funcionan

```
Navegador (Xterm.js + fetch + WebSocket)
        │  HTTP (REST JSON, cookies de sesión + CSRF)
        │  WebSocket (/ws/terminal/)
        ▼
Daphne (servidor ASGI) ── un único proceso Python
        │
        ├── Vistas Django (ctf/views.py)         → CRUD de instancias, retos, settings
        ├── TerminalConsumer (ctf/consumers.py)  → puente WS ⇄ exec del contenedor
        └── Hilo watchdog (ctf/apps.py)          → barre instancias vencidas cada N s
        │
        ▼
docker_client.py (cliente Docker hecho a mano)
        │  HTTP sobre socket Unix (control: crear/parar/listar)
        │  Socket Unix crudo + HTTP Upgrade (datos: stdin/stdout del exec)
        ▼
/var/run/docker.sock → Docker Engine → cgroups + namespaces del kernel
        │
        ▼
Un contenedor + una red bridge "Internal" por estudiante
```

### 3.1 Frontend (`ctf/templates/`, `ctf/static/ctf/`)

No es una SPA: son templates Django renderizados en servidor (`login.html`, `terminal.html`) más JavaScript vanilla (`terminal.js`, `auth.js`), sin React/Vue. Piezas visibles:

- **Terminal** (Xterm.js, vía CDN) — la consola interactiva del contenedor.
- **Catálogo de retos** con filtro por dificultad.
- **Barra de flag** (`#flag-bar`) — oculta hasta que hay una instancia activa; ahí se pega `FLAG{...}` para validarla.
- **Badge de cuenta regresiva** (`#countdown-badge`) — calculado **100% en el cliente** (`created_at` + límite de tiempo del reto, actualizado cada segundo con `setInterval`); no depende del WebSocket ni de una llamada continua al servidor.
- **Modal de victoria** al resolver un reto.
- **Panel de administración oculto** (`#settings-modal`) — solo aparece si el usuario es `is_staff`, y se abre con un gesto oculto (5 clicks seguidos en menos de 1.5 s sobre el nombre de usuario). Tres pestañas: umbrales del watchdog, instancias en vivo (contenedores reales vs. filas en base de datos, para detectar huérfanos), y alta de usuarios sin pasar por `/admin/`.

El frontend habla con el backend por **dos canales separados**:
- **Plano de control** — `fetch()` a `/api/...` (crear/destruir instancia, listar retos, enviar flag, ajustar settings). Autenticado con la cookie de sesión de Django + token CSRF.
- **Plano de datos** — `WebSocket` nativo a `/ws/terminal/`, exclusivamente para la consola interactiva.

### 3.2 Backend (`ctf/views.py`, Django puro sin DRF)

Endpoints principales bajo `/api/`:

| Endpoint | Función |
|---|---|
| `GET /api/challenges/` | catálogo de retos + progreso/XP del usuario |
| `POST /api/challenges/submit/` | valida la flag enviada, otorga XP |
| `GET /api/instance/status/` | estado de la instancia activa del usuario |
| `POST /api/instance/start/` | crea red + contenedor para el reto elegido |
| `POST /api/instance/stop/` | destruye la instancia del usuario |
| `GET/POST /api/platform-settings/` | (solo staff) umbrales del watchdog en caliente |
| `GET /api/platform-settings/instances/` | (solo staff) contenedores reales vs. filas en BD |
| `POST /api/platform-settings/instances/destroy/` | (solo staff) destrucción manual de cualquier instancia |
| `GET/POST /api/platform-settings/users/` | (solo staff) alta de usuarios/staff |

Auth con `django.contrib.auth` estándar (sesiones por cookie); el WebSocket reutiliza esa misma sesión vía `AuthMiddlewareStack` de Channels, así que no hay un segundo sistema de login para la terminal.

El catálogo de retos **no vive en base de datos**: está hardcodeado en `ctf/challenges.py`. Solo se persisten instancias activas y retos resueltos.

### 3.3 Cliente Docker propio (`ctf/docker_client.py`)

No usa `docker-py` ni `dockerode`: habla la API REST de Docker Engine directamente sobre el socket Unix.

- **Operaciones de control** (crear/parar/listar contenedores y redes): peticiones HTTP normales vía `requests-unixsocket`.
- **Operaciones de datos** (la consola interactiva): abre un socket Unix crudo, envía a mano `POST /exec/{id}/start` con `Upgrade: tcp`, procesa la respuesta `101 Switching Protocols`, y a partir de ahí lee/escribe bytes directamente con `sock_recv`/`sock_sendall` no bloqueantes sobre el *event loop* de `asyncio`. Esto reemplazó una versión anterior basada en hilos (`asyncio.to_thread`) que saturaba el pool de hilos de Python (`min(32, CPUs+4)`) alrededor de las **16 consolas simultáneas** — el detalle está documentado en el propio código como razón del rediseño.
- Cada contenedor nace con: `Memory` (256 MB por defecto), `NanoCpus` (0.5 CPU), `PidsLimit` (64 procesos), `ReadonlyRootfs: true`, `Tmpfs` en `/tmp` con `noexec,nosuid`, y `CapDrop: ALL` + solo las capacidades mínimas para que `sudo` funcione dentro del reto.
- Cada usuario recibe su propia red bridge **interna** (`ctf-net-{user_id}-{random}`), sin salida a Internet ni visibilidad hacia otros estudiantes.

### 3.4 WebSocket (`ctf/consumers.py`, `ctf/routing.py`)

Un único endpoint: `ws/terminal/`, atendido por `TerminalConsumer` (Channels `AsyncWebsocketConsumer`).

- Al conectar: verifica sesión autenticada (si no, cierra con código 4001) y que exista una `Instance` activa del usuario (si no, cierra con 4004); luego crea un `exec` (shell) dentro del contenedor del usuario y hace el *hijack* del socket.
- **Protocolo de mensajes:**
  - Frames **binarios** = bytes crudos de teclado/salida del proceso (sin envoltorio, para mínima latencia).
  - Frames de **texto en JSON** = mensajes de control; hoy el único es `{"type": "resize", "rows": N, "cols": N}` para ajustar el TTY cuando el usuario redimensiona la ventana.
- Cada interacción actualiza `last_activity` en la base de datos (con *throttle* de 30 s para no saturar SQLite en comandos como `top` que generan salida continua).
- Al desconectar: cierra el socket *hijacked* y **mata el shell dentro del contenedor** (`kill -9` sobre el PID guardado), para no dejar procesos huérfanos consumiendo el `PidsLimit`.
- El WebSocket **solo** transporta la consola interactiva. El countdown, la lista de retos y el estado de la instancia viajan por REST; no hay un canal de "logs en vivo" separado.

### 3.5 Watchdog (`ctf/watchdog.py`, `ctf/apps.py`, `ctf/management/commands/watchdog.py`)

Proceso de limpieza automática de instancias abandonadas o vencidas. La lógica vive en una sola función (`sweep_stale_instances`) para no duplicarla, y tiene **dos formas de ejecutarse**:

1. **Hilo integrado** (por defecto): `CtfConfig.ready()` lanza un `threading.Thread(daemon=True)` dentro del mismo proceso Daphne, activable/desactivable con `CTF_WATCHDOG_INTEGRADO=1/0`. Corre en loop cada `CTF_WATCHDOG_INTERVAL_SECONDS` (60 s por defecto).
2. **Comando independiente**: `python manage.py watchdog [--once] [--interval N]`, pensado para correrlo como proceso aparte (cron/systemd) si se decide sacarlo del proceso web.

En cada barrido, por cada `Instance` evalúa dos condiciones independientes:
- **Inactividad**: `last_activity` más antigua que `inactivity_timeout_seconds`.
- **Vida máxima absoluta**: tiempo total vivo ≥ el límite según la **dificultad del reto** (evita que un bucle con salida periódica mantenga la instancia viva para siempre solo por parecer "activa").

Si se cumple cualquiera, destruye el contenedor y la red, y borra la fila; si Docker falla al destruir, **no borra la fila** (para reintentar y no dejar un contenedor huérfano sin registro).

**Configuración en caliente:** desde el commit `78266d1` estos umbrales (timeout de inactividad, vida máxima por dificultad) se guardan en el modelo singleton `PlatformSettings`, editable desde `/admin/` o desde el panel oculto del frontend. El watchdog lee siempre el valor actual en cada pasada, así que un cambio tarda como máximo un intervalo de barrido (60 s por defecto) en aplicarse — **sin reiniciar el servidor**.

### 3.6 Base de datos

**SQLite**, con `timeout=20` explícito para tolerar que el WebSocket (actualizando `last_activity`) y el watchdog escriban casi al mismo tiempo. Modelos: `Instance` (una por usuario, `OneToOneField`), `SolvedChallenge` (progreso/XP), `PlatformSettings` (config en caliente). No hay tabla de retos: esos están en código.

---

## 4. Flujo completo (login → contenedor corriendo → destrucción)

1. Login estándar de Django (`/login/`) → sesión por cookie.
2. `terminal.html` carga y `terminal.js` pide `GET /api/challenges/` y `GET /api/instance/status/`.
3. Usuario elige reto → `POST /api/instance/start/`.
4. El backend valida que no tenga ya una instancia activa (protegido a nivel de base de datos por `OneToOneField`, con manejo de condición de carrera si dos peticiones llegan a la vez), crea la red interna, crea y arranca el contenedor con sus límites de recursos, y solo entonces inserta la fila `Instance`.
5. El frontend recibe éxito y abre el WebSocket `/ws/terminal/`.
6. `TerminalConsumer` localiza la instancia, abre un `exec` (shell) en el contenedor y empieza a bombear bytes en ambas direcciones — el estudiante ve el prompt real de su contenedor en Xterm.js.
7. Mientras interactúa, se refresca `last_activity`; en paralelo el watchdog vigila si la instancia venció por inactividad o por tiempo máximo.
8. Al encontrar la flag: `POST /api/challenges/submit/` la valida, suma XP, dispara el modal de victoria.
9. Fin de la instancia: manual (`POST /api/instance/stop/`) o automática (watchdog) — en ambos casos se destruye contenedor + red y se borra el registro.
10. Un `is_staff` puede, en cualquier momento, abrir el panel oculto para ajustar umbrales, ver huérfanos/fantasmas (contenedores reales sin fila en BD, o filas sin contenedor real) y forzar destrucciones.

---

## 5. Seguridad y aislamiento (resumen)

Todo el aislamiento "duro" ocurre a nivel de kernel/Docker, no de aplicación:

- **Red**: bridge interna por usuario, sin ruta por defecto → no hay salida a Internet ni visibilidad entre estudiantes.
- **Cómputo**: `cgroups` limitan memoria, CPU y número de procesos (protección real contra fork-bombs y bucles infinitos — el kernel corta, no un script vigilando).
- **Filesystem**: raíz de solo lectura + `/tmp` en tmpfs sin ejecución ni setuid.
- **Privilegios**: `CapDrop: ALL`, solo se añade lo estrictamente necesario para que `sudo` funcione dentro del reto (cada reto define una regla `sudoers` restringida a un único comando exacto, para que la única vía de escalar sea explotar la vulnerabilidad, no leer el flag directo).

Esto significa que aunque el "orquestador" (Django) tenga un bug, el radio de daño de un estudiante que se escapa de su contenedor está acotado por el propio Docker/kernel, no por lógica de aplicación.

---

## 6. Escalabilidad operativa

Esta es la parte que hoy **no** está resuelta para producción a gran escala; el sistema fue diseñado y probado como un **despliegue de un solo host** (un solo proceso Daphne, un daemon Docker compartido, un archivo SQLite). Puntos concretos:

| Componente | Límite actual | Por qué | Camino de escalado |
|---|---|---|---|
| **Channel layer** (Channels) | `InMemoryChannelLayer` | Vive en la memoria de un único proceso; no coordina WebSockets entre varios workers y se pierde en cada reinicio | Cambiar a `channels_redis` (Redis como backend) para poder correr N réplicas de Daphne detrás de un balanceador |
| **Base de datos** | SQLite, un solo escritor | Suficiente para decenas de usuarios; con más carga concurrente, contención de escritura (`last_activity` + watchdog) | Migrar a PostgreSQL cuando se necesite más de un proceso backend o más concurrencia de escritura |
| **Watchdog** | Hilo dentro del proceso web | Si se escalan horizontalmente varios workers, cada uno lanzaría su propio watchdog salvo que se desactive (`CTF_WATCHDOG_INTEGRADO=0`) y se corra aparte | Ya existe el comando `manage.py watchdog` pensado para correr como proceso/cron único e independiente del número de workers web |
| **Concurrencia de consolas** | Sin techo explícito en config, pero el diseño (sockets no bloqueantes en el *event loop*) fue reescrito justamente porque el enfoque anterior (hilos) colapsaba ~16 consolas simultáneas | El límite real hoy lo marca CPU/RAM del host Docker, no el código | Monitorear file descriptors y el *event loop* de Daphne bajo carga real antes de prometer un número; considerar más de un worker Daphne (requiere resolver el punto de Channel layer primero) |
| **Un solo host Docker** | No hay orquestador (no K8s, no Swarm, no docker-compose para la propia plataforma) | El daemon de Docker es un recurso compartido y único | Para más de un host: habría que introducir un plano de asignación (a qué host mandar cada contenedor) — cambio de arquitectura no trivial, no presente hoy |
| **Servir estáticos** | El propio ASGI de Django los sirve, con no-cache forzado en DEBUG | Aceptable en demo/aula; no pensado para tráfico alto | Poner Nginx/CDN delante en producción (mencionado como pendiente en el propio código) |

**Techo operativo realista hoy**: una única instancia del servicio, en un único host con Docker, atendiendo un curso/clase (decenas de estudiantes concurrentes, cada uno con **como máximo una instancia activa** gracias al `OneToOneField`). Esto es coherente con el propósito declarado del proyecto (plataforma educativa/aula), no con un SaaS multi-tenant de gran escala.

---

## 7. Escalabilidad económica (costo de operar)

El diseño ya incorpora las palancas correctas para controlar costo, aunque hoy se ejecuten en modo "un solo servidor":

- **Costo por estudiante activo, no por estudiante registrado**: como cada instancia se crea bajo demanda y se destruye automáticamente (inactividad o tiempo máximo por dificultad), el costo de cómputo es proporcional a *uso real simultáneo*, no al tamaño del padrón de usuarios. Un curso de 200 alumnos donde solo 20 están conectados a la vez consume recursos de 20, no de 200.
- **Huella por contenedor está acotada y es predecible**: 256 MB RAM / 0.5 CPU / 64 PIDs por defecto (`.env.example`) permiten dimensionar el host con una cuenta simple: `RAM_host / 256MB` ≈ techo teórico de instancias simultáneas antes de saturar memoria (sin contar el propio proceso Django/Daphne ni margen de SO). Ejemplo: un host con 16 GB dedicables a retos soporta del orden de ~50-60 contenedores simultáneos por memoria antes de tocar el límite de CPU o de PIDs del kernel.
- **Sin gasto de licencias ni orquestador pesado**: no hay Kubernetes, no hay `docker-py`, no hay servicios de terceros de pago — el único "runtime" es el Docker Engine del host y SQLite (gratis). Esto reduce el costo de infraestructura a: un host con Docker + un dominio + certificado TLS.
- **Ítem de costo oculto a vigilar**: el hilo watchdog integrado y el `event loop` de Daphne comparten proceso con las vistas HTTP — si se satura el host por muchas consolas abiertas, el mismo proceso que limpia instancias vencidas es el que sirve la web; en el peor caso (host bajo presión), la limpieza se retrasa justo cuando más se necesita liberar recursos. Operativamente conviene alertar sobre uso de RAM/CPU del host, no solo confiar en el watchdog para contener costo.
- **Camino de crecimiento económico** (si el número de estudiantes concurrentes crece más allá de un host):
  1. Verticalizar primero (más RAM/CPU al mismo host) — es la opción más barata dado que el software ya reparte bien los recursos por contenedor.
  2. Solo si se agota lo vertical, migrar a Redis (channel layer) + PostgreSQL + varios workers Daphne detrás de un balanceador — esto habilita escalar el *servicio web*, pero **no** reparte contenedores entre varios hosts Docker (eso exigiría diseño adicional, hoy inexistente).
  3. Evitar sobre-invertir en orquestación (K8s, Swarm) mientras el caso de uso siga siendo "aula/curso": el costo de operar esa complejidad probablemente supere el ahorro, dado que el cuello de botella real hoy es memoria/CPU por contenedor, no orquestación.

**En una frase**: el sistema ya optimiza costo por diseño (contenedores efímeros, límites duros de recursos, sin dependencias de pago), y su límite hoy no es económico sino operativo — un solo proceso/host — por lo que el primer paso de escalado es exclusivamente vertical antes de considerar cualquier cambio arquitectónico.

---

## 8. Riesgos y deuda técnica conocidos

- `InMemoryChannelLayer` y el watchdog integrado impiden hoy correr más de un worker web sin trabajo adicional (ver §6).
- SQLite es un cuello de botella de escritura concurrente a partir de cierta carga.
- No existe límite explícito de instancias simultáneas a nivel de plataforma (solo 1 por usuario); el límite real es "lo que aguante el host".
- `challenge/Dockerfile` (carpeta singular) es un remanente de una iteración anterior, ya no referenciado por el catálogo activo (`ctf/challenges.py`) — candidato a limpieza para evitar confusión.
- No hay `docker-compose.yml` para desplegar la plataforma en sí; el despliegue asumido es manual sobre un host con Docker.

---

## 9. Referencias dentro del repo

- [docs/arquitectura.md](docs/arquitectura.md) — diagrama Mermaid y justificación decisión por decisión.
- `docs/sdd-plataforma-ctf.md` — Software Design Document, citado directamente en comentarios del código (`# SDD 4.1`, etc.).
- `docs/dia-1-...md` a `docs/dia-10-...md` — bitácora de decisiones día a día.
- `ctf/docker_client.py`, `ctf/consumers.py`, `ctf/watchdog.py`, `ctf/apps.py` — código fuente de referencia para cada sección de este documento.
