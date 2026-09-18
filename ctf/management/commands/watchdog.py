"""
`python manage.py watchdog` — destruye instancias inactivas (ver SDD 4.6
y flujo 5.3).

El servidor ya arranca un watchdog integrado (ver `ctf/apps.py`), así que
este comando es la alternativa para correrlo como proceso aparte: cron,
systemd, o a mano para probar. El barrido en sí es el mismo código
(`ctf/watchdog.py`), no una copia.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from ctf.models import PlatformSettings
from ctf.watchdog import sweep_stale_instances


class Command(BaseCommand):
    help = (
        "Destruye contenedor + red de las instancias que superan el umbral "
        "de inactividad."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Ejecuta una sola pasada y termina, en vez de correr en loop.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=None,
            help=(
                "Segundos entre pasadas cuando corre en loop "
                "(por defecto, CTF_WATCHDOG_INTERVAL_SECONDS)."
            ),
        )

    def handle(self, *args, **options):
        interval = options["interval"] or settings.CTF_WATCHDOG_INTERVAL_SECONDS

        self.stdout.write(
            f"Watchdog iniciado (umbral="
            f"{PlatformSettings.actual().inactivity_timeout_seconds}s, "
            f"intervalo={interval}s, once={options['once']})"
        )

        while True:
            destroyed = sweep_stale_instances()
            if destroyed:
                self.stdout.write(f"Instancias destruidas: {destroyed}")

            if options["once"]:
                break
            time.sleep(interval)
