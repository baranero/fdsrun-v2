from django.conf import settings
from django.shortcuts import render

VERSION_DATE = "27.10.2026"


def page(template):
    def view(request):
        return render(request, f"legal/{template}.html", {"company": settings.COMPANY, "results_days": settings.PRICING["results_days"], "version_date": VERSION_DATE})

    return view
