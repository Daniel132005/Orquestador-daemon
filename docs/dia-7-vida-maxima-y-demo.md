# Día 7 — Vida máxima absoluta y pulido de interfaz

**Estado:** completado.
**Objetivo del plan:** día colchón — nada quedó pendiente real del Día 5
(ver [Día 5](dia-5-consola-websocket.md) y [Día 6](dia-6-integracion-y-fuga.md)),
así que se usó en la deuda medida del Día 6 y en un repaso de la interfaz.

**Depende de:** [Día 6 — Integración y fuga](dia-6-integracion-y-fuga.md).

---

## 1. Vida máxima absoluta

El Día 6 midió, no solo sospechó, un hueco real: un bucle que produce
salida periódica (`while true; do date; sleep 3; done &`) mantiene
`last_activity` fresco para siempre, así que el umbral de inactividad solo
nunca lo alcanza. Una instancia así queda viva indefinidamente sin que el
estudiante haga nada.

**Fix:** `INSTANCE_MAX_LIFETIME_SECONDS` (env `CTF_MAX_LIFETIME_SECONDS`,
por defecto 2 horas). `sweep_stale_instances()` ahora destruye una
instancia si se cumple **cualquiera** de las dos condiciones,
independientes a propósito:

```python
vencidas = Instance.objects.filter(
    Q(last_activity__lt=limite_inactividad) | Q(created_at__lt=limite_vida)
)
```

La inactividad sigue protegiendo el caso normal (instancia abandonada sin
salida); la vida máxima cierra el caso que la inactividad no puede ver
(instancia con salida constante, pero sin estudiante presente).

### Verificación

Réplica exacta del escenario del Día 6 §3, con `CTF_MAX_LIFETIME_SECONDS=30`,
`CTF_INACTIVITY_TIMEOUT_SECONDS=99999` (para aislar que la mata la vida
máxima, no la inactividad) y barrido cada 5s:

```console
lanzando bucle CON salida periodica (mantiene last_activity fresco)...
t+    0s   instancia_activa=True   contenedor_vivo=True
t+   11s   instancia_activa=True   contenedor_vivo=True
t+   21s   instancia_activa=True   contenedor_vivo=True
t+   32s   instancia_activa=True   contenedor_vivo=True
t+   34s   instancia_activa=False  contenedor_vivo=False

>>> DESTRUIDA a los 34s, pese a la salida periodica constante
```

**Confirmado.** 34s = 30s de vida máxima + hasta un intervalo de barrido
de más (5s) — el mismo margen "hasta un intervalo completo" que ya se
documentó para el umbral de inactividad. El caso que antes sobrevivía para
siempre en el Día 6 ahora se recicla igual.

Se verificó también que no quedan contenedores ni redes huérfanos tras la
destrucción, y el servidor volvió a su configuración por defecto
(`CTF_MAX_LIFETIME_SECONDS=7200`) al terminar la prueba.

---

## 2. Pulido de interfaz

### 2.1 Bug real: destruir con Docker caído dejaba la consola muerta

En `terminal.js`, el botón "Destruir" cerraba el WebSocket **antes** de
confirmar que `POST /api/instance/stop/` tuvo éxito. Si esa petición
fallaba (por ejemplo, el daemon de Docker no responde — devuelve 502, ver
`stop_instance` en `views.py`), la instancia seguía activa en el servidor
pero el frontend ya había cerrado su única conexión, dejando la terminal
sin forma de volver a escribir hasta recargar la página.

**Fix:** reordenar para cerrar el socket recién después de que la API
confirme el éxito. Si falla, la consola sigue funcionando con normalidad
y el usuario puede reintentar "Destruir" sin perder la sesión.

### 2.2 Información de vida máxima en la interfaz

Se agregó el nuevo campo `max_lifetime_seconds` a `/api/instance/status/`
y una línea en el panel "Destrucción automática" que lo muestra junto al
umbral de inactividad, con el mismo formateador (`formatTimeout`) ya
usado para ese campo. Verificado contra el servidor real: el JSON
devuelve `max_lifetime_seconds: 7200` y se renderiza como **"2 h"**.

---

## 3. Resumen

| Punto | Resultado |
|---|---|
| Vida máxima absoluta | Cierra la deuda del Día 6 — verificado con el mismo escenario que antes sobrevivía para siempre |
| Consola muerta si `stop` falla | Corregido — el socket se cierra solo tras confirmar éxito |
| Panel de vida máxima en la UI | Agregado, verificado contra el servidor real (JSON + render) |

No se preparó un guion de demo como parte de este día — quedó fuera del
alcance elegido para este colchón.
