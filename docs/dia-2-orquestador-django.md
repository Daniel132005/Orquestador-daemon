# Día 2 — Orquestador en Django

**Estado:** completado y verificado
**Objetivo del plan:** un endpoint que crea un contenedor por usuario
autenticado.
**Criterio de aceptación:** un usuario logueado puede pedir su contenedor vía
POST y el contenedor aparece corriendo en `docker ps`.

**Depende de:** [Día 1 — API de Docker sin SDK](dia-1-api-docker-sin-sdk.md).

---

## 1. Resumen

Se montó el proyecto Django completo sobre la capa construida el Día 1: modelo
de datos, endpoints HTTP autenticados y el ciclo de vida de una instancia por
usuario. Se verificó por HTTP real contra el servidor ASGI, comprobando en cada
paso el estado efectivo en Docker.

Además del alcance estricto del día, la implementación **adelantó el Día 3**
(límites de recursos y red aislada), porque el SDD los define juntos en el
`HostConfig` de creación del contenedor. Lo que queda del Día 3 es probarlo de
forma adversarial, no implementarlo.

---

## 2. Estructura del proyecto

```
manage.py
ctf_platform/          # configuración del proyecto
  settings.py          # apps, channels, límites, rutas de BD y socket
  urls.py              # admin, login/logout, /api/, página de consola
  asgi.py              # router HTTP + WebSocket
  wsgi.py
ctf/                   # la aplicación
  docker_client.py     # (Día 1) REST + hijack contra el socket
  models.py            # modelo Instance
  views.py             # /api/instance/status|start|stop
  urls.py
  admin.py
  consumers.py         # (Día 5) TerminalConsumer
  routing.py           # (Día 5) rutas WebSocket
  management/commands/watchdog.py   # (Día 4)
  migrations/0001_initial.py
  templates/ctf/       # login.html, terminal.html
  static/ctf/          # app.css, auth.js, terminal.js
```

---

## 3. Modelo de datos

`ctf/models.py` — un registro por instancia activa:

| Campo | Tipo | Propósito |
|---|---|---|
| `user` | `OneToOneField(User)` | Un usuario = una instancia activa como máximo |
| `container_id` | `CharField(64)` | ID del contenedor en Docker |
| `network_id` | `CharField(64)` | ID de la red aislada |
| `network_name` | `CharField(128)` | Nombre de la red (se usa en `NetworkMode`) |
| `created_at` | `DateTimeField` | Marca de creación |
| `last_activity` | `DateTimeField` | La actualiza el WebSocket en cada mensaje |

El `OneToOneField` es la decisión que impone "una instancia por usuario". Está
documentada como trade-off en el SDD (sección 7): simplifica el MVP a costa de
no soportar varios retos simultáneos por estudiante.

Se reutiliza el sistema de autenticación por defecto de Django
(`django.contrib.auth`), sin modelo de usuario propio.

### Sobre la migración

La migración inicial se escribió a mano (`ctf/migrations/0001_initial.py`),
porque en el momento de crearla no estaban instaladas todas las dependencias
para ejecutar `makemigrations`. Una vez montado el entorno se verificó que
coincide exactamente con el modelo:

```console
$ python manage.py makemigrations --check --dry-run
No changes detected
```

La carpeta `ctf/migrations/` es el registro versionado del esquema y se
mantiene junto al código.

---

## 4. Endpoints

| Método | Ruta | Descripción | Respuestas |
|---|---|---|---|
| `GET` | `/api/instance/status/` | Estado de la instancia del usuario + límites configurados | `200` |
| `POST` | `/api/instance/start/` | Crea red + contenedor y arranca | `201`, `409` si ya tiene una, `502` si Docker falla |
| `POST` | `/api/instance/stop/` | Destruye contenedor y red | `200`, `404` si no tiene instancia |

Los tres exigen sesión iniciada (`@login_required`) y los de escritura exigen
método POST (`@require_POST`) y token CSRF.

`status/` no estaba en el SDD original; se agregó para que la interfaz sepa, al
cargar la página, si el usuario ya tiene una instancia viva (si no, ofrecería
"iniciar" y recibiría un `409`).

### Flujo de `start_instance`

1. Rechaza si el usuario ya tiene una `Instance`.
2. Crea una red Docker con nombre único (`ctf-net-{user_id}-{aleatorio}`) y
   `Internal: true`.
3. Crea el contenedor conectado a esa red, con los límites del `HostConfig`.
4. Lo arranca.
5. Guarda la fila `Instance`.

Si los pasos 3–4 fallan, la red recién creada se elimina antes de responder,
para no dejar redes huérfanas.

### Límites aplicados (adelanto del Día 3)

Configurables por variable de entorno, con estos valores por defecto:

| Parámetro | `HostConfig` | Valor |
|---|---|---|
| Memoria | `Memory` | 256 MB (`268435456`) |
| CPU | `NanoCpus` | 0.5 núcleos (`500000000`) |
| Procesos | `PidsLimit` | 64 |
| Red | `NetworkMode` | la red interna del usuario |

Docker traduce esto a cgroups; el MVP no manipula cgroups a mano.

---

## 5. Problema encontrado: SQLite sobre `/mnt/c`

**Síntoma:** la base de datos funcionaba para lecturas y escrituras aisladas,
pero al escribir desde la consola interactiva (cada tecla actualiza
`last_activity`) el servidor lanzaba:

```
django.db.utils.OperationalError: disk I/O error
  en _touch_activity → UPDATE last_activity
```

**Causa:** el archivo SQLite estaba en `/mnt/c`, el disco de Windows montado en
WSL. Ese filesystem no implementa el bloqueo de archivos que SQLite necesita
para escrituras concurrentes. Es la **misma causa raíz** que impidió crear el
entorno virtual ahí (ver Día 1, sección 4.3).

**Solución:** la ruta de la base pasó a ser configurable:

```python
# ctf_platform/settings.py
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("CTF_DB_PATH", BASE_DIR / "db.sqlite3"),
    }
}
```

En desarrollo sobre WSL se apunta a una ruta del filesystem nativo de Linux
(`~/ctf-data/db.sqlite3`). El motivo quedó comentado en `settings.py`, anotado
en `.env.example` y documentado en el `README.md`, porque es un detalle que no
se deduce leyendo el código y que volvería a morder a cualquiera que clone el
proyecto en Windows.

**Nota:** el fallo se manifestó al probar la consola (Día 5), pero su causa y
su corrección pertenecen a la capa de datos de este día.

---

## 6. Verificación

Prueba por HTTP real contra el servidor ASGI (`daphne`), comprobando el estado
de Docker en cada paso.

### 6.1 Control de acceso

```console
1a) POST /api/instance/start/ sin autenticar y sin token CSRF
    HTTP 403                     ← bloqueado por CSRF

1b) POST /api/instance/start/ sin autenticar pero con CSRF válido
    HTTP 302 -> /login/?next=/api/instance/start/   ← @login_required
```

Las dos capas actúan en orden: CSRF primero, autenticación después.

### 6.2 Ciclo de vida completo

```console
2) Login como 'daniel'... OK: sesion iniciada

3) Contenedores corriendo ANTES:
   (ninguno)

4) POST /api/instance/start/
   HTTP 201
   {"container_id": "b3341f68c77d...", "created_at": "2026-09-16T23:02:53Z"}

5) Contenedores corriendo DESPUES:
   b3341f68c77d  alpine:latest  Up Less than a second

6) Límites aplicados al contenedor (docker inspect):
   Memory=268435456  NanoCpus=500000000  PidsLimit=64  Network=ctf-net-1-6c5b98c6

7) Red del usuario (docker network inspect):
   ctf-net-1-6c5b98c6  Internal=true

8) Segundo POST /api/instance/start/
   HTTP 409 -> {"error": "Ya tienes una instancia activa"}

9) POST /api/instance/stop/
   HTTP 200 -> {"status": "detenida"}

10) Contenedores corriendo AL FINAL:
    (ninguno)

11) Redes ctf-net restantes:
    (ninguna, se limpió correctamente)

DIA 2: OK
```

**El paso 5 es el criterio de aceptación del plan**: un usuario autenticado
pidió su contenedor por POST y aparece corriendo en `docker ps`.

Los pasos 10 y 11 verifican algo que el criterio no pedía pero importa: el
`stop` no deja residuos — destruye contenedor **y** red.

### 6.3 Comprobación desde dentro del contenedor

Para confirmar que los límites no son solo metadatos declarados sino
restricciones que el kernel aplica, se inspeccionaron los cgroups desde dentro
de un contenedor creado con la misma configuración:

```console
MEM:  268435456          ← los 256 MB
CPU:  50000 100000       ← 50000/100000 = 0.5 núcleos
PIDS: 64
IP:   172.23.0.2/16      ← dirección en la red aislada
INTERNET:
  wget: can't connect to remote host (1.1.1.1): Network unreachable
```

El último renglón confirma el efecto de `Internal: true`: el contenedor no
tiene salida a internet.

---

## 7. Lo que queda fuera de este día

- **Prueba adversarial del aislamiento** (Día 3 / Día 6): está verificado que
  cada usuario recibe su propia red interna, pero todavía no se intentó
  romper el aislamiento *desde dentro* de un contenedor, ni con dos usuarios
  simultáneos.
- **Imagen de reto real:** las pruebas usan `alpine:latest` como marcador de
  posición. Todavía no existe una imagen con un reto de seguridad dentro.
- **Watchdog en ejecución** (Día 4): el comando existe y `last_activity` se
  actualiza correctamente, pero el proceso no se está ejecutando, así que hoy
  una instancia abandonada queda viva indefinidamente.
- **Límite global de instancias concurrentes** en el servidor: fuera de
  alcance del MVP según el SDD, sección 8.

---

## 8. Conclusión

El criterio de aceptación se cumplió y se superó: además de crear el contenedor
por usuario autenticado, quedó verificado el ciclo completo (crear → rechazar
duplicado → destruir sin residuos), con los límites de recursos y el
aislamiento de red efectivamente aplicados por el kernel.

El único problema serio del día fue de entorno, no de diseño: SQLite sobre el
disco montado de Windows. Su corrección dejó la ruta de la base configurable,
lo que además facilita el despliegue real.
