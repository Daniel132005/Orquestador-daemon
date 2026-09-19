"""
Barrido de instancias inactivas (ver SDD 4.6 y flujo 5.3).

La lógica vive acá, en un único lugar, porque la usan dos entradas
distintas: el hilo integrado que arranca junto al servidor (`apps.py`) y
el management command `watchdog`. Tenerla duplicada hacía que las dos
copias pudieran divergir.
"""

import logging
from datetime import timedelta

from django.db import close_old_connections
from django.utils import timezone

from . import challenges, docker_client
from .models import Instance, PlatformSettings

logger = logging.getLogger(__name__)


def sweep_stale_instances() -> int:
    """
    Destruye contenedor + red de las instancias que superaron el umbral de
    inactividad O su vida máxima absoluta, y borra su fila. Devuelve
    cuántas destruyó.

    Las dos condiciones son independientes a propósito (ver Día 6, prueba
    2): un bucle que produce salida periódica mantiene `last_activity`
    fresco para siempre, así que confiar solo en inactividad deja una
    instancia viva sin límite mientras el estudiante no la abandone del
    todo. La vida máxima la corta igual, sin importar cuánta actividad
    observable tenga.

    La vida máxima ya no es un único número global (ver Día 15): depende
    de la dificultad del reto de cada instancia
    (`challenges.time_limit_for`), así que hay que calcularla instancia
    por instancia en vez de filtrarla en un solo `WHERE` de la base --
    con la poca cantidad de instancias concurrentes que maneja esta
    plataforma, recorrerlas todas en Python es más simple y no cuesta
    nada de rendimiento real.

    Se llama a `close_old_connections()` al entrar porque esto corre en un
    hilo de larga duración: sin eso, la conexión a la base queda abierta
    indefinidamente y puede quedar inservible.
    """
    close_old_connections()

    config = PlatformSettings.actual()
    ahora = timezone.now()
    limite_inactividad = ahora - timedelta(
        seconds=config.inactivity_timeout_seconds
    )
    destroyed = 0

    for instance in Instance.objects.all():
        inactive_for = (ahora - instance.last_activity).total_seconds()
        alive_for = (ahora - instance.created_at).total_seconds()
        # Se calcula el límite con el `config` ya traído arriba, en vez de
        # `challenges.time_limit_for()`, que consulta `PlatformSettings`
        # otra vez por cada instancia (patrón N+1). Con esto el barrido hace
        # un número fijo de consultas, no una por instancia. `get_challenge`
        # lee el catálogo en memoria, sin tocar la base.
        reto = challenges.get_challenge(instance.challenge)
        limite_vida_seconds = (
            config.time_limit_for_difficulty(reto["difficulty"])
            if reto
            else config.max_lifetime_seconds
        )

        vencida_por_inactividad = instance.last_activity < limite_inactividad
        vencida_por_vida_maxima = alive_for >= limite_vida_seconds

        if not (vencida_por_inactividad or vencida_por_vida_maxima):
            continue

        motivo = "vida máxima" if vencida_por_vida_maxima else "inactividad"
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
