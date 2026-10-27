from django.urls import path

from . import views

app_name = "panel"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("zlecenia/", views.jobs, name="jobs"),
    path("uzytkownicy/", views.users, name="users"),
    path("uzytkownicy/<int:user_id>/", views.user_update, name="user_update"),
    path("maszyny/", views.machines, name="machines"),
    path("maszyny/<int:machine_id>/usun/", views.machine_delete, name="machine_delete"),
    path("dostep/", views.access_log, name="access"),
]
