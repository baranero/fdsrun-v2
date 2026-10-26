from django.urls import path

from . import views

app_name = "jobs"
urlpatterns = [
    path("", views.job_list, name="list"),
    path("nowe/", views.job_new, name="new"),
    path("<str:public_id>/", views.job_detail, name="detail"),
    path("<str:public_id>/start/", views.job_start, name="start"),
    path("<str:public_id>/stop/", views.job_stop, name="stop"),
    path("<str:public_id>/pliki/<str:name>", views.job_file, name="file"),
]
