from django.contrib import admin

from .models import Machine


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("name", "job", "server_type", "ip", "status", "created_at", "deleted_at", "cost_eur")
    list_filter = ("status", "server_type")
    readonly_fields = ("hcloud_id", "created_at", "deleted_at")
