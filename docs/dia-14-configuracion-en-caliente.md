# Día 14 — Configuración del watchdog editable desde /admin/

**Estado:** completado.
**Objetivo:** poder cambiar el umbral de inactividad y la vida máxima
absoluta sin tocar variables de entorno ni reiniciar el servidor.

---

## 1. El problema

Hasta ahora, `INSTANCE_INACTIVITY_TIMEOUT_SECONDS` e
`INSTANCE_MAX_LIFETIME_SECONDS` solo se podían cambiar editando
`CTF_INACTIVITY_TIMEOUT_SECONDS` / `CTF_MAX_LIFETIME_SECONDS` en el
entorno y reiniciando el proceso de `daphne` — nada práctico si alguien
sin acceso a la terminal del servidor necesita ajustarlo (por ejemplo,
durante una clase, para darle más tiempo a un grupo).

## 2. La solución

Un modelo nuevo, `PlatformSettings` (fila única, tipo singleton),
editable desde el admin de Django que ya viene con el proyecto:

- `inactivity_timeout_seconds`
- `max_lifetime_seconds`

`PlatformSettings.actual()` devuelve siempre esa única fila (la crea
con los valores de `settings.py` como default si todavía no existe
ninguna). `ctf/watchdog.py`, `ctf/apps.py`,
`ctf/management/commands/watchdog.py` y `views.instance_status` leen de
ahí en vez de leer directo de `settings`.

El barrido (`sweep_stale_instances()`) llama a `PlatformSettings.actual()`
en cada pasada, así que un cambio hecho en `/admin/` se aplica desde la
**próxima** pasada del watchdog — sin reiniciar nada.

El admin (`ctf/admin.py`) está configurado para que no se pueda ni
agregar una segunda fila ni borrar la única que existe — el
`changelist` redirige directo al formulario de edición, sin el paso
intermedio de una lista de una sola entrada.

## 3. Verificación

Con un superusuario de prueba, vía el flujo real de `/admin/` (login,
`GET` al changelist, `POST` al formulario de edición):

```console
login admin: 302
changelist: 302   (redirige directo a /admin/ctf/platformsettings/1/change/)
guardar: 302

inactivity_timeout_seconds: 120   <- confirmado en la base tras el POST
max_lifetime_seconds: 3600
```

El cambio se aplicó y se leyó de vuelta correctamente desde la base de
datos, confirmando que el formulario del admin efectivamente persiste
en el modelo que el watchdog consulta.

**Precaución tomada:** apenas confirmado que el guardado funciona, se
restauraron los valores a los defaults seguros (900s / 7200s) para no
dejar una instancia real corriendo con un umbral de 120s -- reducirlo
de golpe en un servidor con estudiantes trabajando destruiría instancias
antes de lo esperado. Se confirmó además que el watchdog integrado no
llegó a destruir nada durante la ventana breve de la prueba (sin
ninguna línea de "Destruyendo instancia" en el log del servidor en ese
período).

---

## 4. Resumen

| Punto | Resultado |
|---|---|
| Config editable sin reiniciar el servidor | `PlatformSettings` (singleton) vía `/admin/` |
| Aplica desde | La próxima pasada del watchdog, sin reinicio |
| Restricciones en el admin | Sin alta de una segunda fila, sin baja de la única |
| Verificado | Login admin real → editar → confirmado en la base |
