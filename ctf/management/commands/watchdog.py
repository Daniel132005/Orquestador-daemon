"""
`python manage.py watchdog` — destruye instancias inactivas (ver SDD 4.6
y flujo 5.3). Pensado para correr en loop (por defecto) o una sola vez
(--once), p. ej. desde cron.
"""

import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ctf import docker_client
from ctf.models import Instance


class Command(BaseCommand):
    help = "Destruye contenedor + red de las instancias que superan el umbral de inactividad."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Ejecuta una sola pasada y termina, en vez de correr en loop.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=60,
            help="Segundos entre pasadas cuando corre en loop (por defecto 60).",
        )

    def handle(self, *args, **options):
        self.stdout.write(
            f"Watchdog iniciado (umbral={settings.INSTANCE_INACTIVITY_TIMEOUT_SECONDS}s, "
            f"interval={options['interval']}s, once={options['once']})"
        )
        while True:
            self._sweep()
            if options["once"]:
                break
            time.sleep(options["interval"])

    def _sweep(self):
        cutoff = timezone.now() - timedelta(
            seconds=settings.INSTANCE_INACTIVITY_TIMEOUT_SECONDS
        )
        stale_instances = list(Instance.objects.filter(last_activity__lt=cutoff))

        for instance in stale_instances:
            self.stdout.write(
                f"Destruyendo instancia inactiva de {instance.user}: "
                f"{instance.container_id[:12]}"
            )
            try:
                docker_client.destroy_instance(instance.container_id, instance.network_id)
            except docker_client.DockerClientError as exc:
                self.stderr.write(
                    f"Error destruyendo {instance.container_id[:12]}: {exc}"
                )
                continue
            instance.delete()
