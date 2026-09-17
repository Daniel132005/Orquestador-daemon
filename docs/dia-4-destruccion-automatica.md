# Día 4 — Destrucción automática por inactividad

**Estado:** completado y verificado.
**Objetivo del plan:** que una instancia abandonada no quede corriendo para
siempre.
**Criterio de aceptación:** dejar una instancia sin tocar el tiempo configurado
y que el watchdog la destruya sola.

**Depende de:** [Día 3 — Aislamiento y límites](dia-3-aislamiento-y-limites.md).

---

## 1. Cómo funciona

El barrido vive en un único módulo, [`ctf/watchdog.py`](../ctf/watchdog.py), y
lo usan **dos entradas distintas**:

| Entrada | Cuándo se usa |
|---|---|
| Hilo integrado ([`ctf/apps.py`](../ctf/apps.py)) | Arranca solo junto al servidor. Es el modo normal |
| `python manage.py watchdog` | Proceso aparte: cron, systemd, o a mano para probar |

Tener la lógica en un solo lugar es deliberado: antes estaba duplicada entre
ambos, y dos copias del mismo algoritmo terminan divergiendo.

Cada pasada busca instancias cuyo `last_activity` supere
`CTF_INACTIVITY_TIMEOUT_SECONDS` (15 minutos por defecto) y, para cada una,
destruye contenedor y red y borra la fila. Si Docker falla, **la fila se
conserva** para reintentar en la pasada siguiente: borrarla dejaría un
contenedor que nadie volvería a reclamar.

### Qué cuenta como actividad

`last_activity` se actualiza en dos situaciones:

1. Cuando el estudiante **escribe** en la consola.
2. Cuando el contenedor **produce salida**, como máximo una vez cada 30
   segundos.

El segundo caso importa: sin él, un estudiante que lee la salida de un comando
largo sin teclear sería destruido en plena sesión. El límite de 30 segundos
evita que un proceso parlanchín (`top`, por ejemplo) escriba en la base decenas
de veces por minuto, algo que no aportaría nada porque el barrido ocurre cada
60 segundos.

**Contrapartida conocida:** un proceso que escribe sin parar mantiene la
instancia viva indefinidamente, mientras la pestaña siga abierta. Es
explotable a propósito. La solución sería un segundo límite —una vida máxima
absoluta, independiente de la actividad— que hoy no está implementado.

---

## 2. Verificación

Pruebas con umbral reducido a 40 segundos para no esperar 15 minutos.

```console
PRUEBA 1 — una instancia recién creada NO debe destruirse
  recién creada:    filas=1 contenedores=1 redes=1 [inactiva hace 0s]
  tras 13s:         filas=1 contenedores=1 redes=1 [inactiva hace 13s]
  >>> OK: sigue viva

PRUEBA 2 — al superar el umbral, se destruye SOLA
  ... inactiva hace 43s, sigue viva
  ... inactiva hace 53s, sigue viva
  resultado:        filas=0 contenedores=0 redes=0
  >>> DESTRUIDA SOLA
  >>> limpieza completa: SI

PRUEBA 3 — la actividad la mantiene viva
  simulando tecleo cada 15s durante 70s...
  >>> OK: la actividad la mantuvo viva
```

**El criterio de aceptación se cumple**, y la limpieza es completa: no quedan
ni contenedor, ni red, ni fila.

---

## 3. Problemas encontrados y corregidos

Los tres primeros surgieron al revisar el watchdog integrado antes de probarlo.

### 3.1 El watchdog corría en TODO proceso de Django

`AppConfig.ready()` no se ejecuta solo en el servidor: corre en cualquier
proceso que llame a `django.setup()`. Sin filtro, `migrate`, `shell` o
`createsuperuser` empezaban a destruir contenedores de estudiantes.

Demostrado con un comando inofensivo:

```console
  corriendo 'manage.py shell' 25s con umbral de 5s...
  >>> EL COMANDO DE GESTION DESTRUYO LA INSTANCIA
```

**Primera corrección, insuficiente.** Se excluyeron los comandos de gestión
comparando `sys.argv[0]` con `manage.py`. Pero al probarla apareció una pista:
el log decía `intervalo=60s` cuando se había configurado `20s`. El mensaje no
venía del servidor sino **del propio script de prueba**, que también llamaba a
`django.setup()` y cuyo `argv[0]` no era `manage.py`.

**Corrección definitiva: lista blanca en vez de lista negra.** El watchdog solo
arranca en programas que sirven la aplicación (`daphne`, `uvicorn`, `gunicorn`,
`runserver`), y `CTF_WATCHDOG_INTEGRADO` permite forzarlo o desactivarlo.

El criterio detrás de la elección: ante un programa desconocido conviene **no**
arrancar. Equivocarse hacia ese lado deja contenedores de más; equivocarse
hacia el otro destruye el trabajo de un estudiante en plena sesión.

Verificado en ambas direcciones:

```console
script suelto:  hilos vivos: ['MainThread']  >>> OK: no arrancó el watchdog
servidor:       INFO ctf.apps: Watchdog integrado iniciado (umbral=40s, intervalo=20s)
manage.py shell: >>> OK: la instancia sobrevivió
```

### 3.2 El watchdog no dejaba ningún rastro

El logger `ctf.watchdog` no estaba configurado, así que Django descartaba sus
mensajes: no había forma de saber si estaba funcionando ni qué había
destruido. Un proceso que elimina recursos sin intervención humana **tiene**
que ser observable. Se añadió `LOGGING` a `settings.py`:

```console
2026-09-16 21:32:30 INFO ctf.watchdog: Destruyendo instancia de daniel (13462551c361), inactiva hace 28s
```

### 3.3 Conexión a la base sin cerrar

El barrido corre en un hilo de larga duración, que mantenía su conexión abierta
indefinidamente. Se añadió `close_old_connections()` en cada pasada — relevante
con SQLite, que ya había dado problemas en este proyecto.

### 3.4 `database is locked` y contenedores huérfanos

Al probar cinco peticiones simultáneas de `/api/instance/start/` del mismo
usuario, cuatro fallaban con HTTP 500 y quedaban cuatro contenedores sueltos:

```console
Antes:  1×201, 4×500   →  5 contenedores, 5 redes, 1 fila
```

**Causa:** las llamadas a Docker se habían envuelto en `transaction.atomic()`
para evitar una condición de carrera. Pero eso mantenía la base tomada durante
casi un segundo, y como SQLite admite un solo escritor, las peticiones
concurrentes morían con `OperationalError: database is locked`. Al no ser un
`IntegrityError`, el bloque de limpieza nunca se ejecutaba.

Además, `select_for_update()` no aportaba nada: en SQLite no tiene efecto, y ni
siquiera en PostgreSQL serviría, porque no se puede bloquear una fila que
todavía no existe — que es justo la situación de la carrera.

**Corrección:** Docker fuera de la transacción, y dejar que la restricción
`OneToOneField` decida el ganador. El perdedor recibe `IntegrityError` y limpia
lo suyo. Se añadió además `except DatabaseError` (cualquier fallo de base deja
un contenedor sin respaldo) y un `timeout` de 20 s en las opciones de SQLite,
para que los escritores concurrentes esperen en vez de fallar al instante.

```console
Después: 1×201, 4×409   →  1 contenedor, 1 red, 1 fila
```

### 3.5 Contenedor huérfano cuando el arranque fallaba

Revisando el camino de error se encontró otro: si `create_container` tenía
éxito pero `start_container` fallaba, el manejo de errores **solo borraba la
red**. Reproducido con un contenedor cuyo comando no existe:

```console
contenedor creado: 2963bc7bac3f
start falló como se esperaba
remove_network: OK
resultado: contenedores=1  redes=0
>>> HUERFANO CONFIRMADO
```

El contenedor quedaba en estado `Created` para siempre. Corregido borrando el
contenedor antes que la red, y verificado con el mismo escenario.

---

## 4. Operación

```bash
# Modo normal: el watchdog arranca solo con el servidor
daphne -b 0.0.0.0 -p 8000 ctf_platform.asgi:application

# Como proceso aparte (cron, systemd)
python manage.py watchdog
python manage.py watchdog --once      # una pasada, para probar
```

| Variable | Por defecto | Para qué |
|---|---|---|
| `CTF_INACTIVITY_TIMEOUT_SECONDS` | `900` | Inactividad tolerada antes de destruir |
| `CTF_WATCHDOG_INTERVAL_SECONDS` | `60` | Cada cuánto barre |
| `CTF_WATCHDOG_INTEGRADO` | (automático) | `0` desactiva el hilo integrado; `1` lo fuerza |

---

## 5. Deuda conocida

1. **Vida máxima absoluta.** Un proceso que escribe sin parar mantiene su
   instancia viva mientras la pestaña siga abierta (§1). Un segundo límite,
   independiente de la actividad, lo resolvería.

2. **Contenedores huérfanos por muerte del proceso.** Los caminos de error ya
   están cubiertos, pero si el servidor muere de golpe en la ventana de ~1
   segundo entre crear el contenedor e insertar la fila, ese contenedor queda
   invisible para el watchdog, que solo mira filas.

   Se evaluó implementar un barrido de reconciliación por etiquetas y **se
   descartó por ahora**: el SDD deja los "estados inconsistentes" fuera de
   alcance (§8), la ventana es muy estrecha, y un proceso automático que borra
   recursos introduce más riesgo del que elimina si su filtro está mal. La
   alternativa barata es etiquetar los contenedores al crearlos y limpiarlos a
   mano cuando haga falta.

3. **Un solo proceso.** Si se sirviera con varios workers, cada uno arrancaría
   su propio watchdog y competirían por destruir las mismas instancias. Hoy no
   aplica: el SDD asume un único proceso (§7).
