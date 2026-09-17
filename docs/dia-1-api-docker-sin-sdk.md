# Día 1 — API de Docker sin SDK

**Estado:** completado y verificado
**Objetivo del plan:** confirmar que se puede hablar con el socket del daemon
de Docker sin usar `docker-py`, antes de construir cualquier cosa encima.
**Criterio de aceptación:** poder crear y borrar un contenedor de prueba solo
con peticiones REST, sin ninguna librería de alto nivel.

---

## 1. Resumen

Se construyó `ctf/docker_client.py`, la capa que habla directamente con la
Docker Engine API sobre el socket Unix `/var/run/docker.sock`. Se verificó
end-to-end contra un daemon real: crear una red aislada, crear y arrancar un
contenedor, ejecutar un proceso dentro y leer su salida cruda, y destruir todo.

El día se dio por cerrado cuando la prueba mostró la salida real de un proceso
corriendo dentro del contenedor, viajando por un socket "secuestrado".

---

## 2. Fundamento técnico: qué es el socket de Docker

Este punto es el núcleo del día, así que conviene dejarlo documentado.

`/var/run/docker.sock` **no es un archivo común**. Es un *Unix domain socket*:
un punto de comunicación entre procesos que vive en el árbol de directorios.
Se reconoce por la `s` inicial en sus permisos:

```
srw-rw---- 1 root docker 0 /var/run/docker.sock
^
└── "s" = socket (no "-" de archivo regular)
```

Ocupa 0 bytes porque no almacena nada: es un canal con nombre. El daemon
`dockerd` escucha ahí, y **habla HTTP/1.1 común y corriente** — solo que los
bytes viajan por ese archivo-socket en vez de por un puerto TCP.

Verificación directa, sin ninguna librería:

```console
$ curl -s --unix-socket /var/run/docker.sock -i http://localhost/v1.51/containers/json

HTTP/1.1 200 OK
Api-Version: 1.51
Content-Type: application/json
Server: Docker/28.5.1 (linux)

[]
```

Eso es exactamente `docker ps`. El comando `docker` que usa todo el mundo es
solo un cliente HTTP que hace esto por detrás. De ahí que el requisito del SDD
("sin `docker-py`") sea perfectamente viable: alcanza con saber hacer
peticiones HTTP.

Correspondencia entre comandos y peticiones reales:

| Comando familiar | Petición HTTP sobre el socket |
|---|---|
| `docker ps` | `GET /containers/json` |
| `docker run` | `POST /containers/create` + `POST /containers/{id}/start` |
| `docker rm` | `DELETE /containers/{id}` |
| `docker network create` | `POST /networks/create` |

### Nota de seguridad

Los permisos del socket son `root:docker`. **Pertenecer al grupo `docker`
equivale a ser root en el host**, porque con acceso al socket se puede crear un
contenedor que monte `/` del anfitrión y escapar. El proceso de Django tiene
ese poder. Consecuencia de diseño: el socket **nunca** debe montarse dentro de
los contenedores de los estudiantes. Es la vía de escape más obvia que
intentaría un participante de un CTF, y conviene tenerla presente en las
pruebas de fuga del Día 6.

---

## 3. Implementación

Archivo: `ctf/docker_client.py`.

Se usan **dos mecanismos distintos**, y la razón de esa división es la parte
menos evidente del diseño:

### 3.1 Operaciones normales — `requests-unixsocket`

Crear red, crear/arrancar/detener/borrar contenedor y crear el `exec` son
peticiones HTTP clásicas: petición → respuesta → fin. Se resuelven con
`requests-unixsocket`, que es `requests` enseñado a hablar por un socket Unix
mediante el esquema `http+unix://`.

Funciones: `create_network`, `remove_network`, `create_container`,
`start_container`, `stop_container`, `remove_container`, `destroy_instance`,
`create_exec`, `resize_exec`.

### 3.2 El `exec` interactivo — socket crudo y "hijacking"

Aquí `requests` no sirve. Cuando se pide `POST /exec/{id}/start`, Docker
responde `101 Switching Protocols` y **deja de hablar HTTP**: a partir de ese
byte la conexión se convierte en un canal bidireccional crudo conectado al
stdin/stdout del proceso dentro del contenedor. Es el mismo mecanismo de
upgrade que usa WebSocket.

Como `requests` está diseñado para el ciclo petición→respuesta, se abre el
socket a mano con la librería estándar `socket` y se escribe la petición HTTP
carácter por carácter:

```python
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect("/var/run/docker.sock")

request = (
    f"POST /exec/{exec_id}/start HTTP/1.1\r\n"
    "Host: docker\r\n"
    "Content-Type: application/json\r\n"
    f"Content-Length: {len(body)}\r\n"
    "Connection: Upgrade\r\n"
    "Upgrade: tcp\r\n"
    "\r\n"
).encode() + body

sock.sendall(request)
# se consume la cabecera de la respuesta hasta \r\n\r\n;
# lo que siga ya son bytes crudos del proceso
```

El resultado se envuelve en `HijackedExecSocket`, que expone `send`, `recv` y
`close`. Ese objeto es el que después consume el WebSocket del Día 5.

---

## 4. Problemas encontrados y cómo se resolvieron

### 4.1 En Windows nativo no existe `/var/run/docker.sock`

**Síntoma:** el SDD asume un socket Unix, pero el equipo de desarrollo es
Windows 11 con Docker Desktop. `ls /var/run/docker.sock` no encuentra nada, y
`\\.\pipe\docker_engine` tampoco está accesible.

**Causa:** Docker Desktop ejecuta su daemon dentro de una VM WSL2 propia
(distro interna `docker-desktop`). Ese socket solo existe dentro de esa VM; en
el lado Windows la comunicación va por un named pipe, que no es un socket
`AF_UNIX`.

**Solución adoptada:** instalar una distro Ubuntu en WSL2 y ejecutar todo el
proyecto dentro de ella, activando *Docker Desktop → Settings → Resources →
WSL Integration* para esa distro. Con la integración activada, Docker Desktop
expone el socket real dentro de Ubuntu:

```console
$ ls -la /var/run/docker.sock
srw-rw---- 1 root docker 0 /var/run/docker.sock

$ docker version
Client:  28.5.1  (linux/amd64)
Server:  Docker Desktop 4.49.0 — Engine 28.5.1
```

**Alternativa descartada:** adaptar el cliente al named pipe de Windows con
`pywin32`. Se descartó porque el código dejaría de coincidir con el SDD
("socket Unix") y no serviría tal cual para el despliegue Linux real.

### 4.2 `requests-unixsocket` es incompatible con `urllib3` 2.x

**Síntoma:** la primera ejecución falló con

```
urllib3.exceptions.URLSchemeUnknown: Not supported URL scheme http+unix
requests.exceptions.InvalidURL: Not supported URL scheme http+unix
```

**Causa:** `requests-unixsocket` 0.3.0 no recibe mantenimiento desde ~2016 y
depende de APIs internas de `urllib3` 1.x que cambiaron por completo en la
versión 2.0. Al instalar `requirements.txt` sin fijar versiones, pip resolvió
`urllib3` 2.8.0 y `requests` 2.34.2.

**Solución:** fijar versiones compatibles en `requirements.txt`:

```
urllib3<2.0
requests<2.29
```

Quedaron instaladas `urllib3` 1.26.20 y `requests` 2.28.2. El motivo está
comentado en el propio `requirements.txt` para que nadie las "actualice" sin
entender la consecuencia.

### 4.3 El entorno virtual no puede crearse sobre `/mnt/c`

**Síntoma:** `python3 -m venv .venv` dentro del proyecto (que vive en el disco
de Windows montado en WSL) falla:

```
Error: Command '[...\.venv/bin/python3', '-m', 'ensurepip', ...]'
returned non-zero exit status 1.
```

El venv se crea a medias: sin `pip`.

**Causa:** el filesystem `DrvFs`/9p con el que WSL monta los discos de Windows
no soporta todas las operaciones que `ensurepip` necesita.

**Solución:** crear el entorno virtual en el filesystem nativo de Linux
(`~/.venvs/ctf-platform`) y dejar el código donde está. Se comprobó que en esa
ubicación el venv se crea completo, con `pip` incluido.

---

## 5. Verificación

Se ejecutó un script de humo que importa el `docker_client.py` real y recorre
el ciclo completo contra el daemon:

```console
1) Creando red aislada...
   OK network_id=4ae44806d20c
2) Creando contenedor...
   OK container_id=9984174329fd
3) Arrancando contenedor...
   OK arrancado
4) Creando exec (echo hola-ctf) y haciendo hijack...
   Salida cruda del exec: b'hola-ctf\r\n'
5) Destruyendo contenedor + red...
   OK destruido

DIA 1: OK — se pudo crear, ejecutar y destruir hablando directo con el socket.
```

**El dato que cierra el día es el paso 4.** `b'hola-ctf\r\n'` son los bytes
crudos que salieron de un proceso ejecutándose *dentro* del contenedor,
viajando por el socket secuestrado hasta Python. Eso prueba que el hijacking
funciona, que es la parte técnicamente más delicada de todo el proyecto.

Se verificó además que execs sucesivos sobre el mismo contenedor funcionan
(relevante para el Día 5, donde recargar la página crea un `exec` nuevo):

```console
=== exec #1 ===  salida: b'...echo HOLA-1\r\nHOLA-1\r\n...'  FUNCIONA
=== exec #2 ===  salida: b'...echo HOLA-2\r\nHOLA-2\r\n...'  FUNCIONA
=== exec #3 ===  salida: b'...echo HOLA-3\r\nHOLA-3\r\n...'  FUNCIONA
```

---

## 6. Estado del entorno al cerrar el día

| Componente | Valor |
|---|---|
| Sistema anfitrión | Windows 11 Pro |
| Distro de ejecución | Ubuntu 26.04.1 LTS sobre WSL2 |
| Docker | Desktop 4.49.0 — Engine 28.5.1, API 1.51 |
| Socket | `/var/run/docker.sock` (vía WSL Integration) |
| Python | 3.14.4 |
| Entorno virtual | `~/.venvs/ctf-platform` (fuera de `/mnt/c`) |
| Código del proyecto | `/mnt/c/Users/Daniel/Desktop/contenedores_dinamicos` |

---

## 7. Conclusión

El criterio de aceptación del plan se cumplió: se crean, usan y destruyen
contenedores exclusivamente con peticiones REST sobre el socket Unix, sin
`docker-py` ni ninguna otra librería de alto nivel.

El riesgo que el plan señalaba para este día ("si se complica, todo lo demás se
atrasa") se materializó parcialmente, pero no por la API de Docker en sí sino
por el **entorno**: los tres problemas resueltos fueron de plataforma
(Windows/WSL) y de dependencias, no de la lógica de comunicación con el daemon.
