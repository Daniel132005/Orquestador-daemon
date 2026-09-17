"""
Entrypoint ASGI. Sirve HTTP normal con Django y enruta el WebSocket de la
terminal (`ws/terminal/`) hacia el TerminalConsumer (ver SDD 3 y 4.4).
"""

import os

import django
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ctf_platform.settings")
django.setup()

from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

# Daphne no sirve archivos estáticos por sí solo (a diferencia de
# `runserver`), así que se envuelve la app HTTP con el handler de
# staticfiles. En producción esto lo haría un servidor web delante.
http_application = ASGIStaticFilesHandler(get_asgi_application())

from ctf import routing  # noqa: E402  (import tras django.setup())

application = ProtocolTypeRouter(
    {
        "http": http_application,
        "websocket": AuthMiddlewareStack(URLRouter(routing.websocket_urlpatterns)),
    }
)
