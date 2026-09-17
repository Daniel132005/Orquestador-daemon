from django.contrib import admin

from .models import Instance


@admin.register(Instance)
class InstanceAdmin(admin.ModelAdmin):
    list_display = ("user", "container_id", "network_name", "created_at", "last_activity")
    readonly_fields = ("created_at",)
