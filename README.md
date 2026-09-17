# Plataforma CTF con Contenedores Dinámicos

Cada estudiante autenticado levanta bajo demanda un contenedor Docker aislado
con un reto de seguridad, interactúa con él mediante una consola en el
navegador, y el sistema destruye la instancia cuando queda inactiva.

Implementación siguiendo [sdd-plataforma-ctf.md](sdd-plataforma-ctf.md) y el
[plan de 7 días](plan-mvp-7-dias.md).

## Reportes de avance

- [Día 1 — API de Docker sin SDK](docs/dia-1-api-docker-sin-sdk.md)
- [Día 2 — Orquestador en Django](docs/dia-2-orquestador-django.md)

---

## Requisitos

| Requisito | Versión usada | Por qué |
|---|---|---|
| **Docker** corriendo | Engine 28.5.1 | Sin Docker el proyecto no funciona: es quien crea los contenedores |
| Acceso a `/var/run/docker.sock` | — | Todo el orquestador habla por ese socket Unix |
| Python | 3.11+ (probado en 3.14) | — |
| Linux, o Windows **con WSL2** | Ubuntu 26.04 | En Windows nativo no existe el socket Unix de Docker |

> **Importante:** el proyecto **no arranca contenedores solo** ni funciona sin
> Docker. Docker Desktop (o el daemon de Docker en Linux) tiene que estar
> corriendo antes de levantar el servidor. Si no lo está, la página carga y
> podés loguearte, pero "Desplegar instancia" falla con error 500.

### La ventana de Docker Desktop no es el motor

Cerrar la ventana de Docker Desktop **no apaga Docker**: el motor
(`com.docker.backend` y la VM `docker-desktop`) sigue corriendo en la bandeja
del sistema. Para apagarlo de verdad hay que usar *Quit Docker Desktop* desde
el ícono de la ballena.

Al revés también importa: por defecto Docker Desktop **no arranca solo al
prender la PC**. Después de reiniciar Windows hay que abrirlo a mano antes de
levantar el servidor. Se puede dejar automático en *Settings → General → Start
Docker Desktop when you sign in*.

Para saber si está vivo, sin abrir la ventana:

```bash
docker info --format "Servidor: {{.ServerVersion}} | Corriendo: {{.ContainersRunning}}"
```

---

## Instalación en Windows (WSL2)

El proyecto tiene que ejecutarse **dentro de una distro Linux de WSL2**, no en
Windows nativo: el socket Unix de Docker solo existe ahí.

### 1. Instalar WSL2 con Ubuntu

En PowerShell:

```powershell
wsl --install -d Ubuntu
```

Al terminar se abre una consola de Ubuntu que pide crear un usuario y
contraseña Linux. **Ese paso es interactivo**: hay que completarlo en esa
ventana. Si no aparece, abrí una terminal y ejecutá `wsl -d Ubuntu`.

### 2. Conectar Docker Desktop con Ubuntu

En Docker Desktop: **Settings → Resources → WSL Integration** → activar el
toggle de **Ubuntu** → **Apply & restart**.

Sin este paso, Ubuntu no ve Docker. Comprobalo dentro de Ubuntu:

```bash
ls -la /var/run/docker.sock     # debe existir y empezar con "s"
docker ps                        # debe responder, aunque sea vacío
```

### 3. Instalar dependencias del sistema

Dentro de Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip
```

### 4. Clonar el proyecto y crear el entorno virtual

```bash
git clone <URL-DEL-REPO>
cd contenedores_dinamicos

# OJO: el venv NO puede estar en /mnt/c (ver "Problemas frecuentes")
python3 -m venv ~/.venvs/ctf-platform
~/.venvs/ctf-platform/bin/pip install -r requirements.txt
```

### 5. Configurar las variables de entorno

```bash
cp .env.example .env
nano .env        # ajustar CTF_DB_PATH con tu usuario de Linux
export $(grep -v '^#' .env | xargs)
```

La variable crítica es `CTF_DB_PATH`: la base SQLite **no puede vivir en
`/mnt/c`**. Apuntala a tu home de Linux:

```bash
mkdir -p ~/ctf-data
# en .env:  CTF_DB_PATH=/home/TU_USUARIO/ctf-data/db.sqlite3
```

### 6. Preparar la base de datos y un usuario

```bash
~/.venvs/ctf-platform/bin/python manage.py migrate
~/.venvs/ctf-platform/bin/python manage.py createsuperuser
```

### 7. Descargar la imagen del reto

Mientras no exista una imagen de reto real, se usa `alpine` como marcador:

```bash
docker pull alpine:latest
```

---

## Instalación en Linux

Los pasos 3 a 7 de arriba, sin la parte de WSL. El usuario tiene que estar en
el grupo `docker` para poder usar el socket:

```bash
sudo usermod -aG docker $USER   # cerrar sesión y volver a entrar
```

El venv y la base pueden ir donde quieras (las restricciones de `/mnt/c` no
aplican), así que podés omitir `CTF_DB_PATH` y usar el `db.sqlite3` por
defecto.

---

## Levantar el servidor

```bash
CTF_DB_PATH=$HOME/ctf-data/db.sqlite3 \
CTF_CHALLENGE_IMAGE=alpine:latest \
~/.venvs/ctf-platform/bin/daphne -b 0.0.0.0 -p 8000 ctf_platform.asgi:application
```

Después entrá a **http://localhost:8000/** (funciona también desde el navegador
de Windows, no hace falta hacer nada extra).

> **No uses `manage.py runserver`.** No maneja WebSockets, así que la consola
> interactiva no funcionaría. Tiene que ser `daphne`, que es el servidor ASGI.

### El watchdog (destrucción automática)

Es un **proceso aparte**, en otra terminal. Si no lo ejecutás, las instancias
abandonadas quedan corriendo para siempre:

```bash
CTF_DB_PATH=$HOME/ctf-data/db.sqlite3 \
~/.venvs/ctf-platform/bin/python manage.py watchdog

# una sola pasada, para probar:
... manage.py watchdog --once
```

---

## Variables de entorno

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `CTF_DB_PATH` | `db.sqlite3` del proyecto | Ruta del archivo SQLite. **En WSL, obligatoria** (fuera de `/mnt/c`) |
| `CTF_CHALLENGE_IMAGE` | `ctf-challenge:latest` | Imagen que se levanta por estudiante |
| `DOCKER_SOCKET_PATH` | `/var/run/docker.sock` | Socket del daemon |
| `CTF_MEMORY_LIMIT_MB` | `256` | Límite de memoria por contenedor |
| `CTF_NANO_CPUS` | `500000000` | CPU (500000000 = 0.5 núcleos) |
| `CTF_PIDS_LIMIT` | `64` | Máximo de procesos por contenedor |
| `CTF_INACTIVITY_TIMEOUT_SECONDS` | `900` | Inactividad antes de destruir (watchdog) |
| `DJANGO_SECRET_KEY` | clave de desarrollo | **Cambiar en producción** |
| `DJANGO_DEBUG` | `1` | Poner `0` en producción |

---

## Verificar que quedó bien instalado

Con el servidor corriendo y sesión iniciada, apretá "Desplegar instancia" y
después, en otra terminal:

```bash
docker ps                                   # debe aparecer tu contenedor
docker network ls --filter name=ctf-net     # y su red aislada
```

En la consola del navegador, estos comandos prueban que los límites y el
aislamiento son reales (no texto decorativo):

```sh
cat /sys/fs/cgroup/memory.max    # 268435456  = los 256 MB
cat /sys/fs/cgroup/cpu.max       # 50000 100000 = 0.5 núcleos
cat /sys/fs/cgroup/pids.max      # 64
wget -O- http://1.1.1.1          # "Network unreachable" = sin salida a internet
```

Al apretar "Destruir", el contenedor y la red desaparecen de `docker ps` y
`docker network ls`.

---

## Problemas frecuentes

Todos estos aparecieron de verdad durante el desarrollo.

**`ensurepip is not available` al crear el venv**
El venv está en `/mnt/c` (disco de Windows montado en WSL), y ese filesystem no
soporta las operaciones que `ensurepip` necesita. Creá el venv en el filesystem
nativo de Linux (`~/.venvs/...`) aunque el código siga en `/mnt/c`.

**`django.db.utils.OperationalError: disk I/O error`**
La base SQLite está en `/mnt/c`. Ese filesystem no implementa el bloqueo de
archivos que SQLite necesita para escrituras concurrentes, y la consola escribe
en cada tecla. Apuntá `CTF_DB_PATH` a una ruta de Linux.

**`URLSchemeUnknown: Not supported URL scheme http+unix`**
Se instaló `urllib3` 2.x. `requests-unixsocket` no recibe mantenimiento desde
~2016 y solo funciona con `urllib3` 1.x. Las versiones están fijadas en
`requirements.txt`; no las "actualices" sin leer el comentario.

**Error 500 al apretar "Desplegar instancia"**
Casi siempre es Docker apagado o sin permisos sobre el socket. Comprobá con
`docker ps` desde la misma terminal donde corrés el servidor. El manejo
elegante de "Docker caído" está fuera de alcance del MVP (SDD, sección 8), así
que el error sale crudo.

**La página se ve sin estilos, todo texto plano**
Estás usando `runserver`. `daphne` no sirve archivos estáticos por sí solo; el
proyecto lo resuelve con `ASGIStaticFilesHandler` en `ctf_platform/asgi.py`,
que solo se activa por la vía ASGI. Levantá con `daphne`.

**Los comandos `wsl` se quedan colgados**
Suele haber procesos `wsl.exe` zombis. En PowerShell: `wsl --shutdown`, y si no
alcanza, `Get-Process wsl | Stop-Process -Force`.

---

## Estructura del proyecto

```
manage.py
ctf_platform/          # configuración
  settings.py          # apps, channels, límites, rutas de BD y socket
  urls.py              # admin, login/logout, /api/, consola
  asgi.py              # router HTTP + WebSocket
ctf/                   # la aplicación
  docker_client.py     # REST + hijack del exec contra el socket de Docker
  models.py            # modelo Instance
  views.py             # /api/instance/status|start|stop
  consumers.py         # TerminalConsumer (ws/terminal/)
  routing.py           # rutas WebSocket
  management/commands/watchdog.py
  migrations/          # esquema versionado
  templates/ctf/       # login.html, terminal.html
  static/ctf/          # app.css, auth.js, terminal.js
docs/                  # reportes de avance por día
```

---

## Qué NO está implementado todavía

Para que nadie lo busque en el código:

- **Resultados y puntajes.** No hay flags, ni scoring, ni historial. La fila de
  `Instance` se borra al destruir el contenedor, así que no queda registro de
  lo que hizo cada estudiante. El SDD define esto como plataforma de
  orquestación, no de puntuación.
- **Imagen de reto real.** Se usa `alpine` como marcador de posición.
- **Endurecimiento del contenedor:** filesystem de solo lectura, `cap-drop`,
  perfiles seccomp (SDD, sección 8).
- **Reconexión automática** si se cae el WebSocket.
- **Límite global** de instancias concurrentes en el servidor.
- **Manejo exhaustivo de errores** (Docker caído, estados inconsistentes).

Los trade-offs asumidos a propósito (`InMemoryChannelLayer` en vez de Redis,
una instancia por usuario, SQLite) están explicados en la sección 7 del SDD.
