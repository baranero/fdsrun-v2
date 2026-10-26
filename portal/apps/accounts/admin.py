from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "kind", "trusted", "is_staff", "date_joined")
    list_filter = ("kind", "trusted", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dane", {"fields": ("first_name", "last_name", "kind", "language")}),
        ("Rozliczenia", {"fields": ("trusted", "per_job_limit_pln")}),
        ("Uprawnienia", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Daty", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
