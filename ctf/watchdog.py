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
from django.db.models import Q
from django.utils import timezone

from . import docker_client
from .models import Instance

logger = logging.getLogger(__name__)


def sweep_stale_instances() -> int:
    """
    Destruye contenedor + red de las instancias que superaron el umbral de
    inactividad O la vida máxima absoluta, y borra su fila. Devuelve
    cuántas destruyó.

    Las dos condiciones son independientes a propósito (ver Día 6, prueba
    2): un bucle que produce salida periódica mantiene `last_activity`
    fresco para siempre, así que confiar solo en inactividad deja una
    instancia viva sin límite mientras el estudiante no la abandone del
    todo. La vida máxima la corta igual, sin importar cuánta actividad
    observable tenga.

    Se llama a `close_old_connections()` al entrar porque esto corre en un
    hilo de larga duración: sin eso, la conexión a la base queda abierta
    indefinidamente y puede quedar inservible.
    """
    close_old_connections()

    ahora = timezone.now()
    limite_inactividad = ahora - timedelta(
        seconds=settings.INSTANCE_INACTIVITY_TIMEOUT_SECONDS
    )
    limite_vida = ahora - timedelta(seconds=settings.INSTANCE_MAX_LIFETIME_SECONDS)
    destroyed = 0

    vencidas = Instance.objects.filter(
        Q(last_activity__lt=limite_inactividad) | Q(created_at__lt=limite_vida)
    )

    for instance in vencidas:
        inactive_for = (ahora - instance.last_activity).total_seconds()
        alive_for = (ahora - instance.created_at).total_seconds()
        motivo = (
            "vida máxima"
            if instance.created_at < limite_vida
            else "inactividad"
        )
        logger.info(
            "Destruyendo instancia de %s (%s) por %s: inactiva hace %.0fs, viva hace %.0fs",
            instance.user,
            instance.container_id[:12],
            motivo,
            inactive_for,
            alive_for,
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
