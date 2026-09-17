# Día 9 — Los diez retos OWASP, por dificultad

**Estado:** completado.
**Objetivo:** completar el catálogo hasta cubrir las diez categorías del
OWASP Top 10 (2021), cada una con su dificultad (básico/intermedio/difícil).

**Depende de:** [Día 8 — Retos OWASP seleccionables](dia-8-retos-owasp.md).

---

## 1. Un problema real encontrado antes de escalar

Antes de agregar más retos, se comprobó si los dos existentes (Día 8)
realmente exigían explotar la vulnerabilidad. No era así:

```console
$ docker run --rm ctf-reto-injection-sqli:latest sh -c 'whoami; cat /app/flag.txt'
root
FLAG{injection_bypassa_el_login_sin_clave}
```

La consola corre como `root` dentro del contenedor (nada en el Dockerfile
decía lo contrario), así que **`cat` resolvía el reto sin inyectar nada**.
Lo mismo pasaba con `idor`, leyendo el flag directo del código fuente de
`pedidos.py`. Escalar a diez retos con este defecto habría multiplicado el
problema por diez.

### 1.1 La solución: separación real de privilegios

Patrón adoptado en `challenges/_base/Dockerfile`, común a los diez retos:

- La consola corre como `retador`, un usuario sin privilegios.
- El dato sensible (flag, credenciales, base, estado) es de `root`, modo
  `600`: `retador` no puede leerlo ni escribirlo directo.
- Un `sudo` restringido (`/etc/sudoers.d/reto`, `NOPASSWD`) permite
  ejecutar **exactamente** el comando de la app vulnerable como root, ni
  uno más. Explotar la vulnerabilidad a través de ese comando es la única
  vía para llegar al dato protegido.

Verificado para cada reto, en cuatro pasos: bypass directo (`cat`) falla,
correr la app sin `sudo` falla (no puede abrir el archivo protegido),
correr la app con uso normal no da el flag, y solo explotando la falla
real -- vía el `sudo` permitido -- aparece el flag. `sudo` con cualquier
otro comando (`sudo cat flag.txt`) queda bloqueado, pide contraseña.

### 1.2 Un segundo problema, en cascada: `CapDrop: ALL` rompe `sudo`

Al integrar los retos retocados con la plataforma real (no con `docker run`
suelto) apareció esto:

```
sudo: unable to change to root gid: Operation not permitted
```

`sudo` necesita las capacidades `SETUID`/`SETGID` para completar el cambio
de usuario. `create_container()` (ver Día 6) le aplica `CapDrop: ["ALL"]`
a todo contenedor -- y con eso el kernel le recorta el *bounding set* a
**cualquier** proceso del contenedor, incluyendo uno que llega a `root` por
un binario setuid como `sudo`. Sin esas dos capacidades de vuelta, ningún
reto con este patrón podía funcionar bajo la plataforma real, aunque
funcionara perfecto con `docker run` directo (que no aplicaba ese
`CapDrop`).

**Fix:** `CapAdd: ["SETUID", "SETGID"]` junto al `CapDrop: ["ALL"]`
existente. Se volvió a verificar lo que ya se había probado en el Día 3/6:
esto no reabre el aislamiento de red -- `ping` ya funcionaba sin
`CAP_NET_RAW` (usa un socket ICMP no privilegiado, no algo que dependa de
esta capacidad), y sigue sin haber ruta por defecto en la red `Internal`.
El aislamiento de red nunca dependió de las capacidades; sigue sin
depender de ellas.

---

## 2. Los diez retos

| Slug | OWASP | Dificultad | Vulnerabilidad |
|---|---|---|---|
| `injection-sqli` | A03 - Injection | Básico | SQL armado por concatenación; bypass con `admin' -- ` |
| `idor` | A01 - Broken Access Control | Básico | CLI de pedidos sin comprobar dueño; el pedido `1337` no es tuyo |
| `crypto-debil` | A02 - Cryptographic Failures | Básico | Claves con MD5 sin sal; la de admin está en una wordlist |
| `misconfig` | A05 - Security Misconfiguration | Básico | Backup de config (`config.yaml.bak`) legible por cualquiera |
| `diseno-inseguro` | A04 - Insecure Design | Intermedio | Cupón de descuento sin límite de usos por compra |
| `componente-vulnerable` | A06 - Vulnerable and Outdated Components | Intermedio | `libcalc 1.4.2` evalúa expresiones con `eval()` sin sandbox |
| `auth-fallas` | A07 - Identification and Auth Failures | Intermedio | PIN de 4 dígitos sin límite de intentos ni demora |
| `logging-fallas` | A09 - Security Logging and Monitoring Failures | Intermedio | Token de sesión en texto plano en un log sin monitoreo |
| `integridad-datos` | A08 - Software and Data Integrity Failures | Difícil | `pickle.load()` sin verificar integridad de un archivo editable |
| `ssrf` | A10 - Server-Side Request Forgery | Difícil | Lista negra de host sensible a mayúsculas |

Ningún reto necesitó exponer un puerto ni cambiar el modelo de red del
Día 3: todos son de terminal, ejecutados dentro de la misma consola que ya
existía.

### 2.1 Ajuste sobre la marcha: `diseno-inseguro`

La primera versión guardaba el saldo pendiente en `/app/cuenta.json` para
que persistiera entre corridas del script. Falló contra `ReadonlyRootfs`:

```
OSError: [Errno 30] Read-only file system: '/app/cuenta.json'
```

`/app` es parte del rootfs de solo lectura (Día 3); solo `/tmp` (tmpfs) es
escribible, y un tmpfs se reinicia vacío en cada arranque de contenedor,
así que tampoco sirve para guardar algo entre invocaciones separadas de
`docker exec`. Se rediseñó sin ningún archivo de estado: el cupón repetido
se pasa como varios argumentos en una sola invocación
(`tienda.py BIENVENIDA10 BIENVENIDA10 ...`), todo calculado en memoria
dentro de esa única ejecución. Mismo defecto de diseño, sin necesitar
persistencia.

---

## 3. Verificación

Cada reto se probó primero aislado con `docker run` (bypass bloqueado,
sin `sudo` falla, uso normal no da el flag, explotarlo sí), y después de
punta a punta contra la plataforma real -- login, elegir el slug,
`start_instance`, consola WebSocket, escribir los mismos comandos que
escribiría un estudiante, ver el flag, destruir:

```console
pin real (auth-fallas): 5669
injection-sqli           OK
idor                     OK
crypto-debil             OK
misconfig                OK
diseno-inseguro          OK
componente-vulnerable    OK
auth-fallas              OK
logging-fallas           OK
integridad-datos         OK
ssrf                     OK

>>> 10/10 retos OK
```

(El PIN de `auth-fallas` se generó al azar en el build; para saber qué
mandarle a la consola en esta verificación se lo leyó forzando
`docker run --user root`, algo que un estudiante real no puede hacer --
tiene que fuerza-brutearlo por la consola, sin ese atajo.)

Sin contenedores ni redes huérfanos después de la corrida completa.

---

## 4. Resumen

| Punto | Resultado |
|---|---|
| Bypass trivial (`cat flag.txt`) en los retos existentes | Encontrado y cerrado con separación real de privilegios |
| `sudo` roto por `CapDrop: ALL` bajo la plataforma real | Encontrado al integrar (no al probar aislado); corregido con `CapAdd: SETUID, SETGID` |
| Aislamiento de red tras el `CapAdd` | Reverificado: sigue sin ruta por defecto, sin depender de capacidades |
| Los 10 retos, categoría OWASP + dificultad | Catalogados en `ctf/challenges.py`, verificados de punta a punta contra la plataforma real |
