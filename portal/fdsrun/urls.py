from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import TemplateView

from apps.jobs import downloads


def health(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("healthz", health, name="health"),
    path("konto/", include("apps.accounts.urls")),
    path("konto/zewnetrzne/", include("allauth.urls")),
    path("zlecenia/", include("apps.jobs.urls")),
    path("api/compute/", include("apps.compute.urls")),
    path("api/download/auth", downloads.download_auth, name="download_auth"),
    path("pobierz/<str:public_id>/<str:name>", downloads.download, name="download"),
    path("panel/", include("apps.panel.urls")),
    path("", include("apps.legal.urls")),
    path("admin/", admin.site.urls),
]
