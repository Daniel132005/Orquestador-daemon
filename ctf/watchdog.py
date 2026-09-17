"""
Barrido de instancias inactivas (ver SDD 4.6 y flujo 5.3).

La lógica vive acá, en un único lugar, porque la usan dos entradas
distintas: el hilo integrado que arranca junto al servidor (`apps.py`) y
el management command `watchdog`. Tenerla duplicada hacía que las dos
copias pudieran divergir.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from . import docker_client
from .models import Instance

logger = logging.getLogger(__name__)


def sweep_stale_instances() -> int:
    """
    Destruye contenedor + red de las instancias que superaron el umbral de
    inactividad y borra su fila. Devuelve cuántas destruyó.

    Se llama a `close_old_connections()` al entrar porque esto corre en un
    hilo de larga duración: sin eso, la conexión a la base queda abierta
    indefinidamente y puede quedar inservible.
    """
    close_old_connections()

    cutoff = timezone.now() - timedelta(
        seconds=settings.INSTANCE_INACTIVITY_TIMEOUT_SECONDS
    )
    destroyed = 0

    for instance in Instance.objects.filter(last_activity__lt=cutoff):
        inactive_for = (timezone.now() - instance.last_activity).total_seconds()
        logger.info(
            "Destruyendo instancia de %s (%s), inactiva hace %.0fs",
            instance.user,
            instance.container_id[:12],
            inactive_for,
        )
        try:
            docker_client.destroy_instance(
                instance.container_id, instance.network_id
            )
        except docker_client.DockerClientError as exc:
            # Se deja la fila para reintentar en la próxima pasada: si el
            # daemon está caído, borrarla dejaría el contenedor huérfano.
            logger.error(
                "No se pudo destruir %s: %s", instance.container_id[:12], exc
            )
            continue

        instance.delete()
        destroyed += 1

    return destroyed
