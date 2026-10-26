from django.conf import settings


def site(request):
    return {"ENVIRONMENT": settings.ENVIRONMENT, "SITE_NAME": "fdsrun"}
