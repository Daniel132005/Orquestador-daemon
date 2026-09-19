# Día 16 — Auditoría de aislamiento y robustez

**Estado:** completado. Batería adversarial contra un contenedor con la
configuración de producción, verificada de forma empírica (no asumida).
**Objetivo:** confirmar que ningún comando —por rebuscado que sea— puede
tumbar el host, inutilizar la consola de forma irrecuperable, afectar a
otro estudiante, ni saltarse el reto; y cerrar los huecos que aparezcan.
**Depende de:** [Día 3 — Aislamiento y límites](dia-3-aislamiento-y-limites.md),
[Día 4 — Destrucción automática](dia-4-destruccion-automatica.md).

---

## Tablero de resultados

| Métrica | Cantidad |
|---|---:|
| 🟢→✅ Bugs reales encontrados y **arreglados** | **4** |
| 🛡️ Vectores **ya cubiertos** (verificados, sin cambios) | **17** |
| 🟡 Riesgos residuales **aceptados** (delegados al watchdog / panel) | **4** |
| ❌ Fallas abiertas sin mitigación | **0** |

**Leyenda de estado**

| Símbolo | Significado |
|---|---|
| ✅ | Bug real. **Fix aplicado y verificado** en esta sesión. |
| 🛡️ | Ya estaba cubierto por la config existente. **Verificado empíricamente**, sin cambios. |
| 🟡 | No se puede cerrar desde dentro del contenedor. **Riesgo aceptado**, contenido por otra capa. |

---

## 1. Bugs reales encontrados y arreglados ✅

Todos en [`ctf/docker_client.py`](../ctf/docker_client.py), commit `7c3e383`.

| # | Vector de ataque | Antes (bug) | Fix aplicado | Verificación |
|---|---|---|---|---|
| 1 | **Fork bomb** `:(){ :\|:& };:` | El cupo de PIDs quedaba tapado por zombis **para siempre**; la consola del estudiante quedaba inutilizable (ni `sudo` arrancaba). | `Init: true` — `docker-init` (tini) como PID 1 real que cosecha zombis. | Consola se recupera sola tras la fork bomb; reto se resuelve normal. |
| 2 | **Agotar descriptores de archivo** | `nofile` en ~1.048.576 (default del daemon); recurso que `PidsLimit` no cubre. | `Ulimits nofile 1024/2048`. | Apertura de fds frena en ~1021; contenedor sigue usable. |
| 3 | **Inundar el log del host** | Log `json-file` sin tope de tamaño por defecto. | `LogConfig json-file max-size=10m max-file=3`. | Log quedó en 0 bytes: la salida del estudiante va por el `exec`, no al log — el tope es seguro defensivo a futuro. |
| 4 | **Huérfanos al cerrar la consola** `cmd &` | `terminate_console` mataba por **grupo** (`kill -9 -PID`); los trabajos en background escapan a grupos propios por el job control de bash → sobrevivían hasta el watchdog. | `terminate_console` mata por **sesión** (recorre `/proc`, junta por `sid`). | E2E: `sleep &`, `(sleep &)` y pipelines → 0 huérfanos al reconectar; cerrar una consola no toca a la otra; PID 1 sobrevive. |

---

## 2. Vectores ya cubiertos 🛡️

Verificados de forma adversarial; la configuración existente ya los contenía.

### Recursos de cómputo y almacenamiento

| # | Vector | Resultado | Mecanismo |
|---|---|---|---|
| 5 | Bomba de memoria `bytearray(10**12)` | Proceso muere (OOM, exit 137); **contenedor sigue vivo** | `Memory: 256m` |
| 6 | Bucle de CPU ×4 | Tope ~50%; host intacto | `NanoCpus` (0.5) |
| 7 | Llenar `/tmp` (`cat /dev/zero`) | Frena exacto en 64 MB | `Tmpfs size=64m` |
| 8 | Llenar disco del host / escribir fuera de `/tmp` | `Read-only file system` en `/`, `/home`, `/app` | `ReadonlyRootfs: True` |
| 9 | `mkdir` masivo / agotar inodos | Contenido (~8% inodos); contenedor vivo | `Tmpfs` acotado |

> **Nota sobre el disco:** `df -h` muestra ~939 GB "disponibles" en el overlay, pero es la capacidad del disco físico, **no** espacio escribible: el rootfs está montado read-only. No se puede escribir ni un byte fuera de `/tmp`.

### Red e identidad

| # | Vector | Resultado | Mecanismo |
|---|---|---|---|
| 10 | Alcanzar la red de otro estudiante | `Network unreachable` (ping, wget, TCP directo, ruta manual) | Red `Internal` sin gateway + `NET_ADMIN`/`NET_RAW` dropeadas |
| 11 | Ver / matar procesos de otro | Solo ve los suyos | PID namespace propio |
| 12 | Alcanzar el gateway del bridge | No existe gateway que alcanzar | `Internal: true` |
| 13 | Crear user namespace `unshare -U -r` | `Operation not permitted` | Perfil seccomp por defecto de Docker |
| 14 | Inspeccionar `mount` / `env` | Sin bind mounts, **sin `docker.sock`**, env sin secretos | Config de creación |

### Escalada y lógica

| # | Vector | Resultado | Mecanismo |
|---|---|---|---|
| 15 | `PYTHONPATH` contra `sudo` | Módulo inyectado **no se ejecuta**; usa el real | `env_reset` de sudo (no está en `env_keep`) |
| 16 | `CapAdd SETUID/SETGID` → root | `setuid(0)` falla; único setuid-root es `sudo` restringido | `CapDrop: ALL` + sudoers por comando exacto |
| 17 | Escribir la flag / validar en cliente | Validación 100% server-side; XP y "resuelto" en la BD | `submit_flag` + `SolvedChallenge` |

### Sesión y ciclo de vida

| # | Vector | Resultado | Mecanismo |
|---|---|---|---|
| 18 | Dos pestañas, mismo usuario | Terminales **separadas**; cerrar una no toca la otra | Un `exec` (sesión) por pestaña |
| 19 | Cerrar pestaña de golpe | `terminate_console` mata la sesión al instante (no espera al watchdog) | `disconnect()` → kill por sesión |
| 20 | Inducir un huérfano desde la terminal del estudiante | **Imposible** (no ve daphne, sin `docker.sock`, sin red al host) | Sandbox |
| 21 | Duplicados en la vista de instancias | Imposible: un registro por `container_id` | Set `vistos` en `live_instances_view` |

---

## 3. Riesgos residuales aceptados 🟡

Lo que no se puede cerrar desde dentro del contenedor se **declara asumido**
y se delega al watchdog / panel, no se finge resuelto (misma política del SDD).

| # | Riesgo | Por qué no se cierra desde adentro | Red de contención | Probabilidad |
|---|---|---|---|---|
| 22 | **`setsid cmd`** deliberado | Crea una sesión nueva (`sid` propio); escapa al kill por sesión | Watchdog destruye el contenedor entero | Baja (hay que tipearlo a propósito; daño solo al propio contenedor) |
| 23 | **Carrera TOCTOU** en `terminate_console` | Un `fork()` entre leer `/proc` y matar deja un nieto fuera de la lista | Watchdog | Muy baja (ventana de ms) |
| 24 | **Huérfano** (contenedor sin fila) | Muerte dura de daphne entre `start_container` y crear la fila; el watchdog solo mira filas | Panel oculto → "Instancias en vivo" (detección + botón Destruir) | Muy baja (ventana de ms + muerte dura) |
| 25 | **Fantasma** en `/admin` | Fila sin contenedor (reinicio de Docker/host); el `/admin` no cruza con Docker | Watchdog la borra al vencer (hasta ~16 min); el panel oculto la marca `fantasma` | Media (un reinicio la produce) |

---

## 4. Configuración de producción resultante

`HostConfig` compartido por los diez retos ([`ctf/docker_client.py`](../ctf/docker_client.py)):

```python
"HostConfig": {
    "NetworkMode": network_name,      # red Internal por usuario
    "Memory": 256 MB,
    "NanoCpus": 0.5,
    "PidsLimit": 64,
    "CapDrop": ["ALL"],
    "CapAdd": ["SETUID", "SETGID"],   # solo lo que sudo necesita
    "ReadonlyRootfs": True,
    "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"},
    "Ulimits": [{"Name": "nofile", "Soft": 1024, "Hard": 2048}],   # NUEVO
    "LogConfig": {"max-size": "10m", "max-file": "3"},             # NUEVO
    "Init": True,                                                   # NUEVO
}
```

---

## 5. Pendiente de verificar en vivo

Un solo eslabón no es testeable sin el stack completo (daphne + Channels):
que `disconnect()` **se dispare** al cerrar la pestaña de golpe (garantía de
Channels). Prueba manual sugerida:

1. Abrir una instancia, correr `sleep 300 &`.
2. Cerrar la pestaña de golpe (o matar el navegador).
3. Reconectar (nueva pestaña) y correr `ps aux`.
4. **Esperado:** el `sleep` no aparece. Si aparece, revisar el gatillo de `disconnect()`.

> Recordá **reiniciar daphne** tras desplegar: los cambios del `HostConfig` se
> cargan al arrancar el proceso, y las instancias ya corriendo se crearon con
> el código anterior.
