from django.urls import path

from . import views

app_name = "compute"
urlpatterns = [
    path("jobs/<str:public_id>/spec", views.job_spec, name="spec"),
    path("jobs/<str:public_id>/input", views.job_input, name="input"),
    path("jobs/<str:public_id>/progress", views.job_progress, name="progress"),
    path("jobs/<str:public_id>/files/<str:name>", views.job_upload, name="upload"),
    path("jobs/<str:public_id>/finish", views.job_finish, name="finish"),
]
