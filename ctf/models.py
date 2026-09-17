from django.conf import settings
from django.db import models


class Instance(models.Model):
    """
    Una instancia de reto por usuario (ver SDD 4.2). `OneToOneField`
    porque en este MVP un usuario tiene como máximo una instancia activa
    a la vez (ver trade-off en SDD 7).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ctf_instance",
    )
    container_id = models.CharField(max_length=64)
    network_id = models.CharField(max_length=64)
    network_name = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Instance(user={self.user_id}, container={self.container_id[:12]})"
