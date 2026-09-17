# Día 8 — Retos OWASP seleccionables

**Estado:** completado.
**Objetivo:** que el estudiante pueda elegir, antes de desplegar, entre
más de un reto de seguridad — hasta ahora la plataforma solo levantaba
una imagen fija (`alpine` + `bash`) sin contenido de seguridad real.

**Depende de:** [Día 7 — Vida máxima absoluta y pulido de interfaz](dia-7-vida-maxima-y-demo.md).

> **Corrección posterior (Día 9):** la consola de estos dos retos corría
> como `root`, así que `cat /app/flag.txt` los resolvía sin explotar nada.
> Se corrigió con separación real de privilegios antes de escalar a más
> retos — ver [Día 9](dia-9-owasp-top-10-completo.md#1-un-problema-real-encontrado-antes-de-escalar).
> Los comandos de este documento (`python3 /app/app.py`, sin `sudo`) son
> los de la versión original; la vigente usa `sudo python3 /app/app.py`.

---

## 1. Qué se agregó

Dos retos nuevos, cada uno su propia imagen bajo `challenges/`, mapeados
en un catálogo (`ctf/challenges.py`) que el cliente consulta por slug —
nunca envía una imagen, solo un identificador, así nadie puede pedirle a
la plataforma que levante algo fuera del catálogo.

| Slug | Categoría OWASP | Vulnerabilidad |
|---|---|---|
| `injection-sqli` | A03:2021 - Injection | Login que arma el SQL concatenando texto sin sanitizar |
| `idor` | A01:2021 - Broken Access Control | CLI de pedidos que no comprueba que el pedido consultado sea del usuario autenticado |

Ambos son retos de terminal, no de navegador: se interactúa con ellos
igual que con cualquier otro comando dentro de la consola que ya existía,
sin exponer puertos nuevos ni cambiar el modelo de aislamiento de red del
Día 3.

### 1.1 `injection-sqli`

`python3 /app/app.py` pide usuario y clave y construye la consulta como
texto plano:

```python
consulta = f"SELECT usuario FROM usuarios WHERE usuario = '{usuario}' AND clave = '{clave}'"
```

La clave real de `admin` es aleatoria por build (`secrets.token_hex(32)`,
ver `setup_db.py`) — a propósito, para que la única vía practicable sea
inyectar SQL, no adivinar. El bypass clásico:

```
Usuario: admin' -- 
Clave: (cualquier cosa)
```

el `--` comenta el resto de la consulta, así que la comprobación de clave
nunca se ejecuta.

### 1.2 `idor`

`python3 /app/pedidos.py <id>` devuelve el pedido con ese ID sin
comprobar que pertenezca al usuario autenticado (`invitado`, hardcodeado
en el script). Los pedidos `1001` y `1002` son del propio usuario; el
`1337` es de `admin` y contiene el flag — alcanza con probar otros
números.

---

## 2. Cambios en la plataforma

- `ctf/challenges.py` — catálogo (`slug -> imagen, nombre, categoría OWASP, descripción`).
- `Instance.challenge` (migración `0002_instance_challenge`) — qué reto corre cada instancia.
- `POST /api/instance/start/` ahora lee `{"challenge": "<slug>"}` del cuerpo; sin ese campo usa el reto por defecto. Un slug fuera del catálogo devuelve 400 — nunca llega a Docker.
- `GET /api/challenges/` (nuevo) — catálogo para que el frontend construya el selector.
- `GET /api/instance/status/` — devuelve el reto activo (`slug`, `name`, `owasp`, `description`).
- Frontend (`terminal.html`/`terminal.js`/`app.css`) — tarjetas seleccionables antes de desplegar, con la categoría OWASP y la pista de cómo empezar; el panel lateral muestra el reto de la instancia activa.
- Se retira `CTF_CHALLENGE_IMAGE`: ya no hay una imagen fija, cada reto trae la suya en el catálogo.

---

## 3. Verificación

Se construyeron ambas imágenes y se probó cada vulnerabilidad de forma
aislada, directo con `docker run` (sin pasar por la plataforma), antes de
integrar nada:

```console
--- SQLi: intento normal con clave incorrecta ---
Acceso denegado.

--- SQLi: bypass con inyeccion (admin OK sin clave) ---
Acceso concedido. Bienvenido, admin.
FLAG{injection_bypassa_el_login_sin_clave}

--- IDOR: pedido propio (1001) ---
{"cliente": "invitado", "producto": "Sticker ROOT_LABS", ...}

--- IDOR: pedido ajeno (1337), sin control de acceso ---
{"cliente": "admin", "producto": "Acceso VIP", "flag": "FLAG{idor_nunca_confies_en_el_id_del_cliente}"}
```

Después, de punta a punta contra la plataforma real (login → catálogo →
`start_instance` con cada slug → consola WebSocket → resolver el reto
escribiendo los mismos comandos que un estudiante escribiría → destruir):

```console
catalogo: ['injection-sqli', 'idor'] default: injection-sqli

=== Reto: injection-sqli ===
start (challenge=injection-sqli): HTTP 201
status.challenge: {'slug': 'injection-sqli', 'name': 'Login vulnerable', ...}
flag encontrado en la salida de la consola: True
stop: HTTP 200

=== Reto: idor ===
start (challenge=idor): HTTP 201
status.challenge: {'slug': 'idor', 'name': 'Pedidos sin control de acceso', ...}
flag encontrado en la salida de la consola: True
stop: HTTP 200
```

**Confirmado.** El slug elegido determina la imagen real que arranca, el
estado expuesto por la API coincide con lo elegido, y ambos flags
aparecen resolviendo el reto exactamente como lo haría un estudiante
desde la consola del navegador. Sin contenedores ni redes huérfanos tras
la prueba.

---

## 4. Resumen

| Punto | Resultado |
|---|---|
| Selección de reto por el estudiante | Implementada — catálogo en el backend, slug validado antes de tocar Docker |
| `injection-sqli` (A03 - Injection) | Verificado: clave aleatoria por build, bypass solo por inyección SQL |
| `idor` (A01 - Broken Access Control) | Verificado: pedido ajeno accesible sin ningún control de propiedad |
| Integración completa vía la API real | Verificado de punta a punta, dos retos, mismo usuario, sin huérfanos |
