"""
Settings del proyecto. Ver sección 9 del SDD (Stack Tecnológico) y la
sección 7 (Decisiones de Diseño) para el porqué de InMemoryChannelLayer.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

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

# Imagen usada para el reto de seguridad que se levanta por usuario.
CTF_CHALLENGE_IMAGE = os.environ.get("CTF_CHALLENGE_IMAGE", "ctf-challenge:latest")

# Límites de recursos por contenedor (ver SDD 6 — Aislamiento y Seguridad).
CTF_MEMORY_LIMIT_BYTES = int(os.environ.get("CTF_MEMORY_LIMIT_MB", "256")) * 1024 * 1024
CTF_NANO_CPUS = int(os.environ.get("CTF_NANO_CPUS", str(500_000_000)))  # 0.5 CPU
CTF_PIDS_LIMIT = int(os.environ.get("CTF_PIDS_LIMIT", "64"))

# Umbral de inactividad (segundos) que usa el watchdog para destruir
# instancias abandonadas (ver SDD 4.6 y 5.3).
INSTANCE_INACTIVITY_TIMEOUT_SECONDS = int(
    os.environ.get("CTF_INACTIVITY_TIMEOUT_SECONDS", str(15 * 60))
)

# Cada cuánto barre el watchdog buscando instancias vencidas.
CTF_WATCHDOG_INTERVAL_SECONDS = int(
    os.environ.get("CTF_WATCHDOG_INTERVAL_SECONDS", "60")
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
