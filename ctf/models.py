from django.conf import settings
from django.db import models

from .challenges import DEFAULT_CHALLENGE


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
    challenge = models.CharField(max_length=64, default=DEFAULT_CHALLENGE)
    container_id = models.CharField(max_length=64)
    network_id = models.CharField(max_length=64)
    network_name = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Instance(user={self.user_id}, container={self.container_id[:12]})"


class SolvedChallenge(models.Model):
    """
    Registro persistente de retos completados y XP ganado por usuario.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="solved_challenges",
    )
    challenge_slug = models.CharField(max_length=64)
    solved_at = models.DateTimeField(auto_now_add=True)
    xp_awarded = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("user", "challenge_slug")
        ordering = ["-solved_at"]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.challenge_slug} (+{self.xp_awarded} XP)"

