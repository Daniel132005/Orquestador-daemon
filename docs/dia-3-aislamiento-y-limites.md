# Día 3 — Aislamiento de red y límites de recursos

**Estado:** completado. Aislamiento de red y límites de recursos verificados
de forma adversarial (pruebas 1-10).
**Objetivo del plan:** que cada usuario tenga su propio contenedor sin poder
ver ni tocar el de otro usuario.
**Criterio de aceptación:** probar con dos usuarios que uno no puede alcanzar
el contenedor del otro, y que un proceso dentro del contenedor no puede
comerse toda la memoria/CPU del host.

**Depende de:** [Día 2 — Orquestador en Django](dia-2-orquestador-django.md).

---

## 1. Nota sobre el alcance

Las dos tareas de implementación que el plan asigna a este día (pasar los
límites en el `HostConfig` y crear una red `Internal: true` por usuario) ya
estaban hechas desde el Día 2, porque el SDD las define juntas en el mismo
punto de creación del contenedor.

Lo que este día aporta es **la verificación adversarial**: no comprobar que la
configuración está declarada, sino intentar romperla desde dentro de un
contenedor, que es donde estaría un estudiante.

---

## 2. Preparación

Se creó un segundo usuario sin privilegios (`estudiante`, id=2) junto al
existente (`daniel`, id=1, superusuario) y se desplegó una instancia con cada
uno **de forma simultánea**:

| Usuario | Contenedor | Red | IP |
|---|---|---|---|
| `daniel` | `b7922a1c1270` | `ctf-net-1-0be7f5f0` | `172.22.0.2` |
| `estudiante` | `94269396a458` | `ctf-net-2-ddd1b1df` | `172.23.0.2` |

Cada usuario recibió su propia red, con subredes distintas. El nombre de la red
incluye el id del usuario, lo que facilita auditar a quién pertenece cada una.

Todos los ataques siguientes se lanzaron **desde dentro del contenedor de
`daniel`**, ejecutando los mismos comandos que un estudiante podría escribir en
su consola del navegador.

---

## 3. Prueba 3 — Alcanzar el contenedor de otro usuario

```console
$ ping -c 2 -W 2 172.23.0.2
PING 172.23.0.2 (172.23.0.2): 56 data bytes
ping: sendto: Network unreachable

$ nc -z -w 3 172.23.0.2 22
SIN-RESPUESTA
```

**Resultado: BLOQUEADO.** El contenedor del otro usuario es inalcanzable, tanto
por ICMP como por TCP. El error es `Network unreachable`, no un timeout: el
kernel del contenedor ni siquiera tiene una ruta hacia esa subred, así que
descarta el paquete antes de emitirlo.

---

## 4. Prueba 4 — Escaneo de vecinos en la propia red

```console
$ for i in $(seq 1 12); do ping -c1 -W1 172.22.0.$i && echo VIVO:172.22.0.$i; done
VIVO:172.22.0.1
VIVO:172.22.0.2
```

**Resultado: correcto.** Solo responden dos direcciones: `172.22.0.2` (él
mismo) y `172.22.0.1` (la interfaz del bridge en el lado del host). No hay
ningún otro contenedor en su red, que es justamente el diseño: una red por
usuario, con un solo habitante.

---

## 5. Prueba 5 — Salida a internet

```console
$ wget -T 4 -O- http://1.1.1.1
wget: can't connect to remote host (1.1.1.1): Network unreachable

$ ping -c 2 -W 2 8.8.8.8
ping: sendto: Network unreachable
```

**Resultado: BLOQUEADO.** Es el efecto de `Internal: true`.

La causa raíz se ve en la tabla de rutas del contenedor:

```console
$ ip route
172.22.0.0/16 dev eth0 scope link  src 172.22.0.2
```

**No hay ruta por defecto.** Una red normal de Docker agregaría
`default via 172.22.0.1`; una red interna no lo hace. Sin ruta por defecto, el
contenedor solo puede hablar con su propia subred, y cualquier otro destino
falla inmediatamente con `Network unreachable`. Ese único renglón ausente es lo
que sostiene los resultados de las pruebas 3 y 5.

Detalle secundario: en una red interna, Docker tampoco reporta un `Gateway` en
`NetworkSettings`, lo que es coherente con lo anterior.

---

## 6. Prueba 6 — Alcanzar el host y la propia plataforma

Esta es la prueba con el resultado menos concluyente, y conviene leerla con
cuidado.

### 6.1 El host responde en el bridge

```console
$ ping -c 2 -W 2 172.22.0.1
2 packets transmitted, 2 packets received, 0% packet loss
round-trip min/avg/max = 0.108/0.182/0.256 ms
```

El contenedor **sí alcanza** la interfaz del host en su bridge. Esto es
inherente a cómo funciona una red bridge: el host es un vecino más de esa
subred. `Internal: true` impide salir de la subred, no aísla del host.

### 6.2 Servicios del host

```console
$ wget -T 6 -O- http://172.22.0.1:8000/login/
wget: can't connect to remote host (172.22.0.1): Connection refused

$ for p in 22 80 443 2375 2376 3306 5432 6379 8000 8080; do nc -z -w 2 172.22.0.1 $p; done
(ningún puerto respondió)
```

**Resultado en este entorno: ningún servicio alcanzable.** Pero la causa no es
una defensa del diseño, sino una particularidad del entorno de desarrollo:

- Django corre en la distro **Ubuntu** de WSL2, cuyas interfaces son solo `lo`
  y `eth0` (`172.28.177.238`).
- El bridge `172.22.0.1` **no existe en ese espacio de nombres de red**: vive
  dentro del espacio propio del daemon de Docker Desktop.
- Por eso el puerto 8000 responde `Connection refused`: no hay nada escuchando
  en esa dirección, porque el servidor está en otro sitio.

> **Riesgo a verificar antes de desplegar en producción.** En un servidor Linux
> convencional, donde `dockerd` y Django corren sobre el mismo host, la
> dirección `172.22.0.1` **sí sería** la del host que ejecuta el servidor. Si
> Django escucha en `0.0.0.0:8000`, un estudiante podría alcanzar la plataforma
> desde dentro de su propio contenedor de reto. Este resultado favorable **no
> se transfiere automáticamente** al despliegue real.
>
> Mitigaciones a considerar: que el servidor escuche solo en la interfaz
> pública (no en `0.0.0.0`), o reglas de firewall que bloqueen el tráfico desde
> las subredes de los contenedores hacia los puertos de la plataforma.

---

## 7. Vías de escape clásicas

Revisión del estado de endurecimiento dentro del contenedor:

| Vector | Estado | Valoración |
|---|---|---|
| Socket de Docker montado | `No such file or directory` | **Correcto.** Es la vía de escape más grave y no está expuesta |
| Dispositivos en `/dev` | Solo el conjunto mínimo (`null`, `zero`, `tty`, `pts`...) | Correcto: no hay discos del host |
| Usuario dentro del contenedor | `uid=0(root)` | Conocido: root dentro del contenedor, no del host |
| Capacidades | `CapEff: 0000000000000000` tras aplicar `CapDrop: ["ALL"]` | **Corregido** (ver §7.1) |
| Filesystem raíz | Solo lectura, con `/tmp` en tmpfs de 64 MB | **Corregido** (ver §7.2) |

### 7.1 Endurecimiento aplicado: `CapDrop: ["ALL"]`

La medición inicial mostró el conjunto de capacidades por defecto de Docker
(`CapEff: 00000000a80425fb`). Se añadió `"CapDrop": ["ALL"]` al `HostConfig`
en `create_container`, dejando las capacidades en cero.

Comparación medida, sobre contenedores con la misma configuración de red:

| Operación | Antes | Con `CapDrop: ALL` |
|---|---|---|
| `chown` a otro dueño | Permitido | **Bloqueado** |
| Crear dispositivo (`mknod`) | Permitido | **Bloqueado** |
| Montar un filesystem | Bloqueado | Bloqueado |
| Consola, escritura, ejecución de binarios | Funciona | **Funciona igual** |
| `ping`, `wget`, `nc` | Igual que antes | **Igual que antes** |

**Sin costo funcional.** Conviene aclararlo porque es contraintuitivo: quitar
todas las capacidades **no rompe `ping`**. BusyBox usa sockets ICMP de
datagrama (`SOCK_DGRAM`), que no requieren `CAP_NET_RAW`. Todas las pruebas de
red de este documento siguen siendo válidas tal cual.

### 7.2 Endurecimiento aplicado: filesystem de solo lectura

Al `HostConfig` se añadió:

```json
"ReadonlyRootfs": true,
"Tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"}
```

Comportamiento verificado dentro del contenedor:

| Operación | Resultado |
|---|---|
| Escribir en `/` o `/etc` | **Bloqueado** (solo lectura) |
| Escribir en `/tmp` | Permitido, tope de 64 MB |
| Consola, lectura, ejecutar binarios del sistema | Funciona igual |
| Ejecutar un archivo creado en `/tmp` | **Bloqueado** por `noexec` |
| Correrlo con un intérprete (`sh /tmp/script`) | **Funciona** |

**Matiz sobre `noexec`, importante al diseñar los retos.** La bandera impide
que el kernel ejecute directamente un archivo depositado en `/tmp`, pero no
impide que un intérprete lo lea: `./exploit.sh` falla y `sh exploit.sh`
funciona. En la práctica frena binarios compilados, no scripts.

Si algún reto necesitara que el estudiante compile y ejecute un binario
propio, habría que darle un directorio sin `noexec`. Hoy no aplica: la imagen
no trae compilador y la red interna impide descargar uno.

### 7.3 Las capacidades no aíslan la red

Un experimento de control conviene dejarlo registrado, porque corrige una
intuición equivocada frecuente: se puso un contenedor con **cero capacidades**
en la **misma red** que su vecino.

```console
capacidades efectivas: 0000000000000000
ping 172.23.0.2 -> 64 bytes from 172.23.0.2: seq=0 ttl=42 time=4.070 ms
```

Lo alcanzó sin dificultad. **Quitar capacidades no aporta absolutamente nada
al aislamiento entre estudiantes**: eso lo sostiene, entero, la ausencia de
ruta que provoca `Internal: true`.

Son dos capas ortogonales:

- **La ruta ausente** impide llegar a otras redes. Bloquea a cualquier
  programa, sin excepción.
- **`cap-drop`** reduce lo que un proceso puede hacer *dentro* de su propio
  contenedor, encareciendo la escalada si alguien compromete el reto.

Si el aislamiento de red fallara, ninguna cantidad de capacidades quitadas lo
compensaría.

---

## 8. Resumen de las pruebas 1-6

| # | Prueba | Resultado |
|---|---|---|
| 1 | Dos usuarios con instancias simultáneas | Correcto, redes separadas |
| 2 | Red y contenedor propios por usuario | Correcto |
| 3 | Alcanzar el contenedor del otro usuario | **Bloqueado** |
| 4 | Escanear vecinos de la propia red | Solo él mismo y el host |
| 5 | Salida a internet | **Bloqueado** |
| 6 | Alcanzar host y plataforma | Host visible por ICMP; sin servicios alcanzables *en este entorno* (ver advertencia §6.2) |

**El criterio de aceptación relativo al aislamiento entre usuarios se
cumple:** un estudiante no puede alcanzar el contenedor de otro, verificado
activamente y no solo por configuración declarada.

---

## 9. Límites de recursos bajo ataque (pruebas 7-10)

Los ataques se lanzaron desde el contenedor de `daniel`. El contenedor de
`estudiante` actuó como **testigo**: debía seguir respondiendo con normalidad
durante todo el proceso. La plataforma se consultó por HTTP en cada etapa para
medir si el host se degradaba.

### 9.1 Prueba 7 — Agotar la memoria (límite: 256 MB)

**Primer intento, y por qué su resultado era engañoso.** Se usó una tubería
(`head | tail`) para retener 400 MB. El proceso no murió: se quedó colgado
hasta agotar el tiempo de la prueba, y el contador `oom_kill` siguió en 0. Leído
de forma superficial, parecía que el límite no actuaba.

Lo que en realidad ocurrió se vio en `docker stats` durante la prueba
siguiente: el contenedor estaba clavado en **255,4 MiB / 256 MiB**. El límite sí
actuaba, pero conteniendo por *estancamiento* — el kernel bloqueaba al proceso
en lugar de matarlo, porque una tubería puede esperar indefinidamente.

**Verificación limpia.** Se repitió en contenedores desechables con límites
idénticos, sin tocar las instancias de los usuarios.

Asignación progresiva (12 procesos de 40 MB cada uno = 480 MB solicitados):

```console
lanzados=1   uso=22339584
lanzados=4   uso=78118912
lanzados=8   uso=153509888
lanzados=12  uso=240353280
--- eventos ---
max       280      ← veces que se alcanzó el techo
oom        10      ← eventos de falta de memoria
oom_kill    1      ← procesos efectivamente eliminados
--- pico ---
268435456
Killed
```

Un solo proceso pidiendo 600 MB:

```console
max        22
oom         1
oom_kill    1
Killed
```

**El dato decisivo es el pico: `268435456` bytes = exactamente 256 MB.** Ni un
byte por encima del límite configurado. Cuando los procesos insistieron, el
kernel eliminó uno (`oom_kill 1`).

**Resultado: CONTENIDO.** El límite es infranqueable. El mecanismo concreto
varía según cómo se pida la memoria (estancamiento con tuberías, muerte por OOM
con asignación anónima), pero en ningún caso el contenedor obtuvo más de lo
asignado.

### 9.2 Prueba 8 — Saturar la CPU (límite: 0,5 núcleos)

Se lanzaron **cuatro bucles infinitos simultáneos** dentro del contenedor.
Medición con `docker stats` durante la carga:

```console
silly_wu          54.77%   255.4MiB / 256MiB     ← atacante
vigilant_kapitsa   0.00%   680KiB / 256MiB       ← testigo
---
silly_wu          51.56%
vigilant_kapitsa   0.00%
---
silly_wu          49.58%
vigilant_kapitsa   0.00%
```

**Resultado: CONTENIDO.** Cuatro procesos que intentaban consumir cuatro
núcleos completos quedaron topados en ~50 % de uno solo, exactamente el
`NanoCpus=500000000` configurado. El testigo permaneció en 0,00 % y la
plataforma respondió en **8 ms** durante la carga (contra 15 ms en reposo).

### 9.3 Prueba 9 — Fork bomb (límite: 64 procesos)

Se ejecutó una bomba de bifurcación real (`bomba() { bomba | bomba & }`)
durante 8 segundos. Después del ataque, el propio contenedor no podía crear ni
un proceso más:

```console
sh: can't fork: Resource temporarily unavailable
```

Mientras tanto:

```console
plataforma durante el fork bomb: HTTP 200 en 12 ms
testigo durante el fork bomb:    vivo-27
```

**Resultado: CONTENIDO.** El `PidsLimit=64` absorbió el ataque por completo. El
contenedor atacante quedó saturado —que es el precio que paga quien lanza el
ataque contra sí mismo— pero ni el host ni el otro usuario lo notaron. Una vez
terminados los procesos, el contenedor volvió a aceptar comandos con
normalidad.

### 9.4 Prueba 10 — Estado final

```console
plataforma:            HTTP 200 en 19 ms
testigo (estudiante):  vivo-32
eventos de memoria del testigo:  low 0  high 0      ← sin incidentes
contenedores vivos:
  94269396a458  alpine:latest  Up 9 minutes
  b7922a1c1270  alpine:latest  Up 42 minutes
```

Tras tres ataques consecutivos, el host respondió con normalidad, ambos
contenedores seguían en pie y el usuario testigo nunca registró un solo evento
de presión de memoria.

---

## 10. Resumen de las pruebas 7-10

| # | Ataque | Límite | Resultado |
|---|---|---|---|
| 7 | Reservar memoria sin freno | 256 MB | **Contenido** — pico exacto de 268435456 B, con `oom_kill` |
| 8 | 4 bucles infinitos de CPU | 0,5 núcleos | **Contenido** — topado en 49-55 % |
| 9 | Fork bomb | 64 procesos | **Contenido** — `can't fork`, host intacto |
| 10 | Estado del host y del testigo | — | Sin degradación (8-19 ms en todo momento) |

**El criterio de aceptación del Día 3 se cumple por completo:** un usuario no
puede alcanzar el contenedor de otro, y un proceso dentro de un contenedor no
puede comerse la memoria ni la CPU del host.

---

## 11. Conclusiones y deuda identificada

Lo que funciona y quedó probado activamente:

- Aislamiento de red entre usuarios, sostenido por la ausencia de ruta por
  defecto en redes `Internal: true`.
- Límites de memoria, CPU y procesos, aplicados por cgroups y verificados
  bajo ataque real.
- El socket de Docker no está expuesto dentro de los contenedores.
- Capacidades del kernel en cero (`CapDrop: ["ALL"]`), sin costo funcional.

Lo que queda pendiente de atender:

1. **Acceso del contenedor al host** (§6.2). En este entorno no se alcanzó
   ningún servicio, pero por una particularidad de Docker Desktop, no por
   diseño. **Debe reverificarse en el despliegue real.**
2. **Endurecimiento del contenedor**: ya están aplicados `cap-drop ALL`
   (§7.1) y el filesystem de solo lectura con `/tmp` en tmpfs (§7.2). Queda
   pendiente que el proceso no corra como root dentro del contenedor, y los
   perfiles seccomp. Declarado fuera de alcance en el SDD §8.
3. **Sin límite global de instancias**: nada impide que N usuarios levanten N
   contenedores hasta agotar el host. Cada contenedor está limitado, pero el
   total no. También está en el SDD §8.
Los tres puntos anteriores estaban anticipados por el SDD (§8).

### Hallazgo no previsto, ya corregido

Las pruebas de carga posteriores revelaron un problema que el SDD no
anticipaba: **cada consola abierta bloqueaba un hilo del servidor de forma
permanente**, y las conexiones que morían sin cerrarse limpiamente no lo
liberaban nunca. Con un pool de 16 hilos, la plataforma se atascaba alrededor
de las 16 consolas y `POST /instance/start/` dejaba de responder mientras el
resto del sitio seguía funcionando.

Se corrigió pasando la lectura del socket del `exec` a `loop.sock_recv()`, que
asyncio atiende de forma nativa sin ocupar hilos. Verificado: 20 de 20 consolas
simultáneas funcionando, contra 0 de 20 antes. El detalle, la medición
comparada y el método de diagnóstico están en la
[guía de pruebas manuales](guia-pruebas-manuales.md#e2--el-límite-de-consolas-simultáneas-hallazgo-y-corrección).
