# Plan de 7 Días — MVP Plataforma CTF

Plan diario para llegar a una demo funcional que cubra: orquestación de
contenedores por usuario, aislamiento de red, límites de recursos,
destrucción automática por inactividad y consola interactiva en el
navegador.

**Regla general:** si un día se atrasa, el recorte va primero sobre el
"modo difícil" (afinar límites, watchdog más sofisticado), nunca sobre la
consola interactiva — eso es lo que hace que la demo se vea funcionando.

---

## Día 1 — API de Docker sin SDK

**Objetivo:** confirmar que puedes hablar con el socket de Docker sin
`docker-py` antes de construir nada encima.

**Tareas:**
- Montar entorno con Docker corriendo.
- Probar peticiones HTTP directas al socket (`requests-unixsocket` o
  `http.client`) para crear, listar y destruir un contenedor a mano.

**Listo cuando:** puedes crear y borrar un contenedor de prueba solo con
peticiones REST, sin ninguna librería de alto nivel.

**Riesgo:** si este día se complica, todo lo demás se atrasa — no lo
saltes ni lo dejes a medias.

---

## Día 2 — Orquestador en Django

**Objetivo:** endpoint que crea un contenedor por usuario autenticado.

**Tareas:**
- Modelo `Instance` (usuario ↔ container_id).
- Vista `start_instance` que crea y arranca el contenedor.
- Reutilizar el sistema de autenticación por defecto de Django.

**Listo cuando:** un usuario logueado puede pedir su contenedor vía POST
y ves el contenedor corriendo con `docker ps`.

---

## Día 3 — Límites de recursos y red aislada

**Objetivo:** que cada usuario tenga su propio contenedor sin poder ver
ni tocar el de otro usuario.

**Tareas:**
- Pasar `Memory`, `NanoCpus`, `PidsLimit` en el `HostConfig` al crear el
  contenedor.
- Crear una red Docker `Internal: true` por usuario.

**Listo cuando:** probaste con dos usuarios que uno no puede alcanzar el
contenedor del otro, y que un proceso dentro del contenedor no puede
comerse toda la memoria/CPU del host.

---

## Día 4 — Destrucción automática por inactividad

**Objetivo:** que una instancia abandonada no quede corriendo para siempre.

**Tareas:**
- Campo `last_activity` en el modelo.
- Management command (`watchdog`) que revisa el timestamp y destruye
  contenedor + red si se pasó del límite.

**Listo cuando:** dejas una instancia sin tocar el tiempo configurado y
el watchdog la destruye solo.

---

## Día 5 — Puente WebSocket + Xterm.js (día crítico)

**Objetivo:** consola interactiva real desde el navegador.

**Tareas:**
- Configurar Django Channels (ASGI, `routing.py`, `consumers.py`).
- Crear un `exec` vía la API de Docker y hacer el "hijack" del socket.
- Reenviar bytes en ambas direcciones entre el WebSocket del navegador y
  el socket del exec.

**Listo cuando:** escribes un comando en la terminal del navegador y ves
la salida real del contenedor.

**Riesgo:** esta es la parte más delicada técnicamente. Pruébala aislada
(un script suelto que solo haga exec + attach) antes de conectarla con
Channels y el frontend — depurar los dos problemas a la vez es mucho
más lento.

---

## Día 6 — Pruebas de integración y de fuga

**Objetivo:** confirmar que lo construido realmente aísla y limita, no
solo que "funciona en el camino feliz".

**Tareas:**
- Simular 2-3 usuarios conectados a la vez.
- Intentar romper el aislamiento de red a propósito.
- Meter un bucle infinito dentro de un contenedor y confirmar que los
  límites de recursos y el watchdog lo controlan.

**Listo cuando:** los intentos de romper el aislamiento fallan como se
espera, y el sistema sigue respondiendo bajo carga básica.

---

## Día 7 — Buffer y demo

**Objetivo:** llegar a la presentación con algo estable, no perfecto.

**Tareas:**
- Resolver lo que quedó pendiente del día 5 (casi seguro algo queda).
- Pulir la interfaz mínima.
- Preparar una demo clara que muestre, en este orden: aislamiento entre
  usuarios → límites de recursos → destrucción automática → consola
  interactiva funcionando.

**Nota:** este día es colchón, no relleno. Si todo salió a tiempo, úsalo
para lo que quedó en la sección "fuera de alcance" del SDD (por ejemplo,
mejorar el manejo de errores).
