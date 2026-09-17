import logging
import os
import sys
import threading
import time

from django.apps import AppConfig

logger = logging.getLogger("ctf.apps")

_watchdog_started = False


# Programas que sirven la aplicación. Solo en ellos tiene sentido reciclar
# instancias automáticamente.
_SERVER_ENTRYPOINTS = {"daphne", "uvicorn", "gunicorn", "hypercorn"}


def _is_server_process() -> bool:
    """
    `AppConfig.ready()` se ejecuta en TODO proceso que llame a
    `django.setup()`: `migrate`, `shell`, `createsuperuser`, y también
    cualquier script suelto. Sin este filtro, cualquiera de ellos
    empezaría a destruir los contenedores de los estudiantes.

    El criterio es una lista blanca, no una lista negra: ante un programa
    desconocido se prefiere NO arrancar el watchdog. Equivocarse hacia el
    lado de no reciclar deja contenedores de más; equivocarse hacia el
    otro lado destruye el trabajo de un estudiante en plena sesión.

    `CTF_WATCHDOG_INTEGRADO` permite forzarlo ("1") o desactivarlo ("0"),
    por ejemplo si se sirve con un programa que no está en la lista o si
    se prefiere correr el watchdog como proceso aparte.
    """
    forzado = os.environ.get("CTF_WATCHDOG_INTEGRADO")
    if forzado is not None:
        return forzado == "1"

    if os.path.basename(sys.argv[0] or "") in _SERVER_ENTRYPOINTS:
        return True

    return "runserver" in sys.argv


class CtfConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ctf"
    verbose_name = "Plataforma CTF"

    def ready(self):
        """
        Arranca el watchdog de inactividad como hilo daemon junto al
        servidor, para no depender de que alguien deje abierta otra
        terminal. El hilo muere cuando se apaga el servidor, así que no
        puede quedar huérfano. El management command `watchdog` sigue
        disponible para correrlo por separado (cron, systemd).
        """
        global _watchdog_started

        if _watchdog_started or not _is_server_process():
            return
        _watchdog_started = True

        threading.Thread(
            target=self._watchdog_loop, name="ctf-watchdog", daemon=True
        ).start()

    @staticmethod
    def _watchdog_loop():
        from django.conf import settings

        from .watchdog import sweep_stale_instances

        interval = settings.CTF_WATCHDOG_INTERVAL_SECONDS

        # Dar tiempo a que Django termine de arrancar antes del primer
        # barrido, para no consultar la base a medio inicializar.
        time.sleep(10)

        logger.info(
            "Watchdog integrado iniciado (umbral=%ss, intervalo=%ss)",
            settings.INSTANCE_INACTIVITY_TIMEOUT_SECONDS,
            interval,
        )

        while True:
            try:
                sweep_stale_instances()
            except Exception:
                # Un error inesperado no debe matar el hilo: si lo hiciera,
                # la plataforma dejaría de reciclar instancias en silencio.
                logger.exception("Error inesperado en el watchdog")

            time.sleep(interval)
