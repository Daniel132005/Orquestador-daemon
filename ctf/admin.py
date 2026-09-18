from django.contrib import admin

from .models import Instance, PlatformSettings, SolvedChallenge


@admin.register(Instance)
class InstanceAdmin(admin.ModelAdmin):
    list_display = ("user", "challenge", "container_id", "network_name", "created_at", "last_activity")
    readonly_fields = ("created_at",)


@admin.register(SolvedChallenge)
class SolvedChallengeAdmin(admin.ModelAdmin):
    list_display = ("user", "challenge_slug", "xp_awarded", "solved_at")
    readonly_fields = ("solved_at",)


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    """
    Fila única: no tiene sentido borrarla ni agregar una segunda, así
    que se deshabilita "agregar" y "borrar" -- solo queda editarla.
    """

    list_display = (
        "inactivity_timeout_seconds",
        "time_limit_basico_seconds",
        "time_limit_intermedio_seconds",
        "time_limit_dificil_seconds",
        "max_lifetime_seconds",
        "updated_at",
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Ir directo a editar la única fila en vez de mostrar una lista
        # de una sola entrada -- no aporta nada ese paso intermedio.
        PlatformSettings.actual()
        obj = PlatformSettings.objects.first()
        from django.shortcuts import redirect
        return redirect("admin:ctf_platformsettings_change", obj.pk)
