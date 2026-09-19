"""
Settings del proyecto. Ver sección 9 del SDD (Stack Tecnológico) y la
sección 7 (Decisiones de Diseño) para el porqué de InMemoryChannelLayer.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Este default solo sirve para desarrollo local (DEBUG=True). Vive en el
# código fuente, así que es PÚBLICO: nunca debe usarse en producción.
_INSECURE_SECRET_KEY = "dev-only-insecure-secret-key"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _INSECURE_SECRET_KEY)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# La SECRET_KEY firma las cookies de sesión y los tokens CSRF. Con el default
# público, cualquiera podría forjar una cookie que diga "soy staff" y entrar al
# panel oculto sin conocer ninguna clave -- y el chequeo `is_staff` no lo
# frenaría, porque la cookie sería válida. Por eso se aborta el arranque antes
# que servir en producción (DEBUG=False) con la clave de desarrollo.
if not DEBUG and SECRET_KEY == _INSECURE_SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY no está definida y DEBUG=False. Definí una clave "
        "aleatoria antes de desplegar, por ejemplo:\n"
        "  python -c \"import secrets; print(secrets.token_urlsafe(64))\"\n"
        "y pasala en la variable de entorno DJANGO_SECRET_KEY."
    )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "ctf",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ctf_platform.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ctf_platform.wsgi.application"
ASGI_APPLICATION = "ctf_platform.asgi.application"

# InMemoryChannelLayer: suficiente para un solo proceso/demo (ver SDD 7).
# No escala a múltiples workers ni sobrevive a un reinicio.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

# El archivo SQLite NO puede vivir en un disco de Windows montado en WSL
# (/mnt/c/...): ese filesystem no implementa el bloqueo que SQLite necesita
# y las escrituras concurrentes fallan con "disk I/O error". En WSL hay que
# apuntar CTF_DB_PATH a una ruta del filesystem nativo de Linux.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("CTF_DB_PATH", BASE_DIR / "db.sqlite3"),
        "OPTIONS": {
            # SQLite admite un solo escritor a la vez, y aquí escriben a
            # la vez todas las consolas abiertas (`last_activity`) más el
            # watchdog. Sin `timeout`, el segundo escritor falla al
            # instante con "database is locked"; con él, espera su turno.
            "timeout": 20,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"

# --- Configuración específica de la plataforma CTF ---

CTF_PLATFORM_VERSION = "v0.1.0"

# Ruta al socket Unix del daemon de Docker (ver docker_client.py).
DOCKER_SOCKET_PATH = os.environ.get("DOCKER_SOCKET_PATH", "/var/run/docker.sock")

# La imagen a levantar ya no es fija: la elige el estudiante entre el
# catálogo de `ctf/challenges.py`, y cada entrada trae su propia imagen.

# Shell que abre la consola. Vacío = detección automática: usa `bash` si la
# imagen lo trae (activa `bracketed paste`, que impide que un texto pegado se
# ejecute solo) y `sh` si no. Se puede forzar uno concreto.
CTF_CONSOLE_SHELL = os.environ.get("CTF_CONSOLE_SHELL", "")

# Límites de recursos por contenedor (ver SDD 6 — Aislamiento y Seguridad).
CTF_MEMORY_LIMIT_BYTES = int(os.environ.get("CTF_MEMORY_LIMIT_MB", "256")) * 1024 * 1024
CTF_NANO_CPUS = int(os.environ.get("CTF_NANO_CPUS", str(500_000_000)))  # 0.5 CPU
CTF_PIDS_LIMIT = int(os.environ.get("CTF_PIDS_LIMIT", "64"))

# Umbral de inactividad (segundos) que usa el watchdog para destruir
# instancias abandonadas (ver SDD 4.6 y 5.3).
INSTANCE_INACTIVITY_TIMEOUT_SECONDS = int(
    os.environ.get("CTF_INACTIVITY_TIMEOUT_SECONDS", str(15 * 60))
)

# Cada cuánto barre el watchdog buscando instancias vencidas. A 5s la
# destrucción por vida máxima / inactividad se siente casi inmediata (el
# countdown llega a 0 y el contenedor cae a lo sumo 5s después, no 60);
# el costo de barrer más seguido es despreciable con pocas instancias.
CTF_WATCHDOG_INTERVAL_SECONDS = int(
    os.environ.get("CTF_WATCHDOG_INTERVAL_SECONDS", "5")
)

# Vida máxima absoluta de una instancia, sin importar su actividad (ver
# Día 6: un bucle que produce salida periódica mantiene `last_activity`
# fresco para siempre y el umbral de inactividad solo, nunca la alcanza).
# Este techo la destruye igual una vez cumplido, medido desde `created_at`.
INSTANCE_MAX_LIFETIME_SECONDS = int(
    os.environ.get("CTF_MAX_LIFETIME_SECONDS", str(2 * 60 * 60))
)

# El watchdog destruye contenedores sin intervención humana, así que tiene
# que dejar rastro: sin esto sus mensajes se pierden y no hay forma de
# saber si está funcionando ni qué destruyó.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "ctf": {
            "format": "{asctime} {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "ctf",
        },
    },
    "loggers": {
        "ctf": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
