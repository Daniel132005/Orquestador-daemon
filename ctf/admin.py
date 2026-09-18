from django.contrib import admin

from .models import Instance, SolvedChallenge


@admin.register(Instance)
class InstanceAdmin(admin.ModelAdmin):
    list_display = ("user", "challenge", "container_id", "network_name", "created_at", "last_activity")
    readonly_fields = ("created_at",)


@admin.register(SolvedChallenge)
class SolvedChallengeAdmin(admin.ModelAdmin):
    list_display = ("user", "challenge_slug", "xp_awarded", "solved_at")
    readonly_fields = ("solved_at",)
