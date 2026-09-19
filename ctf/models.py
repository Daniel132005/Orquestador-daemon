from django.conf import settings
from django.db import models

from .challenges import DEFAULT_CHALLENGE, TIME_LIMITS


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
    # Intentos de bandera erronea acumulados en ESTA instancia. Al llegar
    # al tope (ver views.MAX_INTENTOS_BANDERA) la instancia se destruye.
    # Vive en la instancia a proposito: redesplegar arranca una fila nueva
    # con el contador en 0, asi que el limite se resetea al redesplegar.
    failed_flag_attempts = models.PositiveIntegerField(default=0)

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


class OnboardingState(models.Model):
    """
    Estado de onboarding por usuario. Hoy solo registra si ya vio el
    tutorial de bienvenida, para mostrarlo una sola vez (la primera vez
    que inicia sesión). Vive en la BD (no en localStorage) para que sea
    por-persona y sobreviva a cambios de navegador/dispositivo.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="onboarding",
    )
    tutorial_visto = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Onboarding(user={self.user_id}, tutorial_visto={self.tutorial_visto})"


class PlatformSettings(models.Model):
    """
    Configuración editable en caliente desde /admin/, sin tocar
    variables de entorno ni reiniciar el servidor (ver
    docs/dia-14-configuracion-en-caliente.md).

    Fila única (singleton): `actual()` siempre trabaja sobre la
    primera fila, creándola con los valores de `settings.py` como
    default si todavía no existe ninguna.
    """

    inactivity_timeout_seconds = models.PositiveIntegerField(
        default=settings.INSTANCE_INACTIVITY_TIMEOUT_SECONDS,
        help_text=(
            "Segundos sin actividad en la consola antes de que el "
            "watchdog destruya la instancia."
        ),
    )
    max_lifetime_seconds = models.PositiveIntegerField(
        default=settings.INSTANCE_MAX_LIFETIME_SECONDS,
        help_text=(
            "Vida máxima absoluta para un reto que no está en el "
            "catálogo (ej. una instancia vieja de un reto ya "
            "eliminado) -- para los retos normales manda el límite "
            "por dificultad de más abajo."
        ),
    )
    time_limit_basico_seconds = models.PositiveIntegerField(
        default=TIME_LIMITS["basico"],
        help_text="Vida máxima de un reto básico, en segundos.",
    )
    time_limit_intermedio_seconds = models.PositiveIntegerField(
        default=TIME_LIMITS["intermedio"],
        help_text="Vida máxima de un reto intermedio, en segundos.",
    )
    time_limit_dificil_seconds = models.PositiveIntegerField(
        default=TIME_LIMITS["dificil"],
        help_text="Vida máxima de un reto difícil, en segundos.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración de la plataforma"
        verbose_name_plural = "Configuración de la plataforma"

    def __str__(self) -> str:
        return "Configuración de la plataforma"

    @classmethod
    def actual(cls) -> "PlatformSettings":
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj

    def time_limit_for_difficulty(self, difficulty: str) -> int:
        return {
            "basico": self.time_limit_basico_seconds,
            "intermedio": self.time_limit_intermedio_seconds,
            "dificil": self.time_limit_dificil_seconds,
        }.get(difficulty, self.time_limit_basico_seconds)

