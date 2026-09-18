"""
Entrypoint ASGI. Sirve HTTP normal con Django y enruta el WebSocket de la
terminal (`ws/terminal/`) hacia el TerminalConsumer (ver SDD 3 y 4.4).
"""

import os

import django
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf import settings
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ctf_platform.settings")
django.setup()

from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402


class _NoCacheStaticApp:
    """
    Fuerza revalidación en cada pedido a `/static/` durante desarrollo.

    `ASGIStaticFilesHandler` sirve esos pedidos ANTES de que lleguen a la
    app de Django (y a su `MIDDLEWARE`) — por eso un middleware normal de
    Django no sirve para esto, hay que envolver un nivel más afuera, acá.
    Sin esto, `Last-Modified` sin `Cache-Control` deja que el navegador
    use su propia heurística de caché, y puede seguir ejecutando una
    versión vieja de `terminal.js`/`app.css` sin volver a pedirla nunca
    (ver docs/dia-12-cache-de-estaticos.md).
    """

    def __init__(self, app):
        self.app = app
        self._prefix = ("/" + settings.STATIC_URL.lstrip("/")).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].encode().startswith(self._prefix):
            return await self.app(scope, receive, send)

        async def send_sin_cache(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_sin_cache)


# Daphne no sirve archivos estáticos por sí solo (a diferencia de
# `runserver`), así que se envuelve la app HTTP con el handler de
# staticfiles. En producción esto lo haría un servidor web delante.
http_application = ASGIStaticFilesHandler(get_asgi_application())
if settings.DEBUG:
    http_application = _NoCacheStaticApp(http_application)

from ctf import routing  # noqa: E402  (import tras django.setup())

application = ProtocolTypeRouter(
    {
        "http": http_application,
        "websocket": AuthMiddlewareStack(URLRouter(routing.websocket_urlpatterns)),
    }
)
