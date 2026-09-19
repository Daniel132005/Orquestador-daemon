# Glosario técnico — Contenedores Dinámicos

Glosario de términos para entender la arquitectura y el dominio de la plataforma (CTF con contenedores Docker efímeros por usuario/reto).

## Stack y tecnologías

- **Django**: framework web en Python que da estructura al backend (modelos, vistas, ORM, panel de administración en `/admin`).
- **Django Channels**: extensión de Django que añade soporte para WebSockets y protocolo ASGI (necesario para la consola en vivo).
- **ASGI (Asynchronous Server Gateway Interface)**: sucesor asíncrono de WSGI; permite manejar conexiones persistentes como WebSockets. Definido en `ctf_platform/asgi.py`.
- **Daphne**: servidor ASGI usado para correr el proyecto. Se usa en vez de `manage.py runserver` porque este último no soporta WebSockets.
- **WSGI**: interfaz síncrona clásica de Python para servir HTTP; queda en `wsgi.py` pero no es la vía usada para la consola en vivo.
- **SQLite**: base de datos del proyecto (`db.sqlite3`); su ruta es configurable con la variable de entorno `CTF_DB_PATH`.
- **Docker Engine**: motor de contenedores que crea y destruye los entornos de cada reto.
- **Socket Unix de Docker (`/var/run/docker.sock`)**: vía de comunicación local con el Docker Engine, usada directamente por HTTP (sin el SDK oficial de Docker) mediante `requests-unixsocket`.
- **Xterm.js**: librería JavaScript que renderiza una terminal interactiva en el navegador (con el addon `xterm-addon-fit` para ajustar el tamaño).
- **WSL2 (Windows Subsystem for Linux)**: requerido en Windows porque el socket Unix de Docker no existe de forma nativa en Windows; el proyecto corre dentro de una distro Ubuntu.

## Estructura del proyecto

- **`ctf_platform/`**: proyecto Django raíz (settings, urls, punto de entrada ASGI/WSGI).
- **`ctf/`**: app principal de Django, contiene toda la lógica del dominio CTF.
- **`challenges/`**: Dockerfiles de cada reto de seguridad, más una imagen base común (`_base` → `ctf-base`).
- **`docs/`**: documentación de diseño (SDD) y bitácora de avance del proyecto.

## Modelos y componentes clave (`ctf/`)

- **`docker_client.py`**: cliente propio (no usa el SDK oficial) que habla con Docker vía HTTP sobre el socket Unix, para crear/borrar redes y contenedores, abrir sesiones "exec" y redimensionar la terminal.
- **`consumers.py` / `TerminalConsumer`**: puente entre el WebSocket del navegador y el proceso "exec" dentro del contenedor; reenvía bytes en ambas direcciones para dar la sensación de consola en vivo.
- **`watchdog.py`**: proceso en segundo plano que revisa cada 60 segundos las instancias activas y destruye las que están inactivas o superaron su tiempo máximo de vida.
- **`challenges.py`**: catálogo de retos disponibles, con su categoría, imagen Docker, flag, XP, dificultad y límites de tiempo.
- **`views.py`**: endpoints HTTP del sistema (listar retos, enviar flag, iniciar/detener instancia, ver estado, panel de administración, vista de instancias en vivo, etc.).

## Términos de dominio

- **Contenedor dinámico**: contenedor Docker aislado que se crea bajo demanda para un usuario y un reto específico, y se destruye automáticamente cuando ya no se usa.
- **Instancia (`Instance`)**: registro que vincula a un usuario con su contenedor y red activos (relación uno a uno: un usuario solo puede tener una instancia activa a la vez).
- **Reto (challenge)**: ejercicio de seguridad tipo CTF, asociado a una categoría del OWASP Top 10, con una dificultad, una flag y puntos de experiencia (XP).
- **Flag**: cadena secreta (formato `FLAG{...}`) que el usuario debe encontrar al explotar la vulnerabilidad del reto; se valida contra el backend al enviarla.
- **Flag-bar**: barra de la interfaz que muestra el estado del reto en curso (pendiente o resuelto) mientras hay una instancia activa.
- **XP (experiencia)**: puntos que gana un usuario al resolver un reto, acumulados a través del modelo `SolvedChallenge`.
- **Watchdog**: proceso que vigila periódicamente las instancias activas y elimina las que expiraron, para liberar recursos del servidor.
- **Vida máxima (max lifetime)**: tiempo tope absoluto que puede vivir una instancia, configurable según la dificultad del reto, sin importar si está en uso.
- **Timeout de inactividad**: tiempo sin actividad en la consola tras el cual el watchdog destruye la instancia.
- **Temporizador de cuenta atrás / countdown badge**: elemento visual que muestra cuánto tiempo le queda a la instancia antes de expirar, con avisos visuales cuando se acerca el límite.
- **Modal de victoria**: ventana emergente que aparece al resolver un reto, mostrando el XP obtenido.
- **Panel oculto / modal de configuración**: panel de administración accesible desde la consola, con pestañas para configurar la plataforma, gestionar usuarios y ver instancias en vivo.
- **Vista de instancias en vivo**: panel que lista los contenedores activos en el servidor y permite destruirlos manualmente.
- **`PlatformSettings`**: configuración global de la plataforma (timeouts, límites de vida por dificultad) editable desde el panel de administración sin necesidad de reiniciar el servidor.
- **OWASP Top 10 (2021)**: catálogo de las diez categorías de vulnerabilidades web más comunes; cada reto de la plataforma corresponde a una de ellas (inyección, IDOR, criptografía débil, mala configuración, diseño inseguro, componentes vulnerables, fallas de autenticación, fallas de registro/logging, fallas de integridad de datos, SSRF).
- **Exec hijacking**: técnica que usa el cliente de Docker para "engancharse" a un proceso `exec` dentro del contenedor y transmitir su entrada/salida como si fuera una terminal real.
- **Aislamiento de red**: cada instancia recibe su propia red Docker, para evitar que los contenedores de distintos usuarios puedan verse o comunicarse entre sí.
- **Usuario "retador"**: usuario sin privilegios dentro de cada contenedor de reto; solo puede llegar a `root` explotando la vulnerabilidad concreta del ejercicio, nunca leyendo la flag directamente (el archivo de la flag tiene permisos restringidos, solo accesibles por `root`).
- **Bracketed paste**: protección de la terminal que evita que un texto pegado se ejecute línea por línea de forma accidental.
