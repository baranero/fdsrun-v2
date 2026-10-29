from django.urls import path

from . import downloads, views

app_name = "jobs"
urlpatterns = [
    path("", views.job_list, name="list"),
    path("pulpit/", views.dashboard, name="dashboard"),
    path("nowe/", views.job_new, name="new"),
    path("<str:public_id>/", views.job_detail, name="detail"),
    path("<str:public_id>/wykresy.json", views.job_charts, name="charts"),
    path("<str:public_id>/konsola/", views.job_console, name="console"),
    path("<str:public_id>/start/", views.job_start, name="start"),
    path("<str:public_id>/edytuj/", views.job_edit, name="edit"),
    path("<str:public_id>/usun/", views.job_delete, name="delete"),
    path("<str:public_id>/stop/", views.job_stop, name="stop"),
    path("<str:public_id>/kontynuuj/", views.job_continue, name="continue"),
    path("<str:public_id>/pliki/<str:name>", views.job_file, name="file"),
    path("<str:public_id>/linki/", downloads.share_links, name="share"),
    path("<str:public_id>/synchronizuj/", views.job_sync, name="sync"),
    path("<str:public_id>/spakuj/", views.job_snapshot, name="snapshot"),
]
