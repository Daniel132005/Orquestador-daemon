# Día 10 — Guía real por reto (objetivo, primer paso, qué esperar)

**Estado:** completado.
**Objetivo:** que quien entra a un reto sepa qué tiene que lograr y por
dónde arrancar, sin tener que adivinarlo por prueba y error.

**Depende de:** [Día 9 — Los diez retos OWASP, por dificultad](dia-9-owasp-top-10-completo.md).

---

## 1. El problema

Con solo la descripción corta de cada tarjeta (la vulnerabilidad, en una
frase, con el comando pegado adentro del texto), quien recién arranca
tiende a copiar mal el comando (falta un espacio, se deja el `<id>`
literal) y, si lo copia bien, no siempre entiende qué se espera que haga
con el resultado. Un caso real durante las pruebas: alguien corrió
`sudo python3/app.pedidos.py <id>` tal cual, con el marcador de
posición incluido, y no relacionaba el error de sintaxis con el reto en
sí.

## 2. Qué se agregó

Un mockup de referencia proponía una interfaz mucho más elaborada
(puntaje, tiempo límite, topología de red, "instructor disponible"). Se
descartó reproducir esas partes: no existen como funcionalidad real en
la plataforma, y el proyecto viene evitando desde el Día 5 cualquier
indicador que no refleje un dato real (ver `terminal.js`, `auth.js`).
En su lugar, cada reto en `ctf/challenges.py` ahora trae tres campos
nuevos, siempre con datos reales sobre lo que ESE reto en particular
hace:

- **`objective`** — qué hay que lograr, en una frase concreta.
- **`first_step`** — el comando exacto para ver el comportamiento
  normal de la app, antes de intentar explotar nada.
- **`expected_result`** — qué se ve al correr `first_step` sin explotar
  todavía nada (para saber si algo salió distinto a lo esperado).

Se muestran en dos lugares:

1. **Al elegir un reto** (antes de desplegar): aparece un recuadro con
   los tres campos, con un botón "Copiar" sobre el primer paso —
   pensado para pegarlo en la consola con `Ctrl+V` (el pegado seguro
   del Día 5).
2. **Con la instancia activa**: el mismo recuadro, más compacto, queda
   fijo en el panel lateral mientras se usa la consola — no hay que
   volver a la pantalla de selección para recordar qué hacer.

## 3. Verificación

Contra la API real: el catálogo (`/api/challenges/`) y el estado de una
instancia activa (`/api/instance/status/`) devuelven los tres campos
nuevos para los diez retos:

```console
catalogo[0] campos: ['description', 'difficulty', 'expected_result',
                      'first_step', 'name', 'objective', 'owasp', 'slug']
objective: Iniciar sesión como admin sin conocer su clave.
first_step: sudo python3 /app/app.py
expected_result: Te pide usuario y clave. Si probás con datos normales...

start idor: 201
status.challenge: {'slug': 'idor', ..., 'objective': 'Encontrar un
pedido que no es tuyo.', 'first_step': 'sudo python3 /app/pedidos.py
1001', 'expected_result': 'Vas a ver TU pedido...'}
```

Sin contenedores huérfanos tras la prueba.

---

## 4. Resumen

| Punto | Resultado |
|---|---|
| Guía por reto (objetivo/primer paso/qué esperar) | Agregada a los 10 retos, con datos reales |
| Visible antes y durante el uso del reto | Recuadro en el selector + panel lateral fijo |
| Copiar el primer comando | Botón "Copiar" + pegado seguro (Ctrl+V, Día 5) |
| Elementos decorativos del mockup de referencia (puntaje, topología, instructor) | Descartados a propósito — no reflejan funcionalidad real |
