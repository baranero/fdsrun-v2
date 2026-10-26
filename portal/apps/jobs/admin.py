from django.contrib import admin

from .models import Job, JobEvent


class JobEventInline(admin.TabularInline):
    model = JobEvent
    extra = 0
    readonly_fields = ("at", "actor", "kind", "detail")
    can_delete = False


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("public_id", "name", "owner", "status", "procs", "server_type", "est_hours", "wall_seconds", "cost_eur", "price_pln", "created_at")
    list_filter = ("status", "server_type")
    search_fields = ("public_id", "name", "owner__email", "chid")
    readonly_fields = ("public_id", "agent_token", "analysis", "created_at", "started_at", "finished_at")
    inlines = [JobEventInline]
