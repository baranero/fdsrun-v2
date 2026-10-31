from django.conf import settings


def site(request):
    return {"ENVIRONMENT": settings.ENVIRONMENT, "SITE_NAME": "fdsrun", "company": settings.COMPANY, "pricing": settings.PRICING, "social_providers": settings.SOCIAL_PROVIDERS_ENABLED}


def nav(request):
    """Liczniki w lewym pasku: zlecenia w toku, faktury do zapłaty, nieopłacone saldo i limit."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from apps.billing import services
    from apps.billing.models import Invoice
    from apps.jobs.models import Job

    try:
        active = Job.objects.filter(owner=user, status__in=Job.ACTIVE, hidden_at__isnull=True).count()
        due = Invoice.objects.filter(user=user, status=Invoice.Status.ISSUED).count()
        balance = None if services.exempt(user) else services.balance(user)
        limit = None if balance is None else services.limit_for(user)
    except Exception:  # pasek nie może wywrócić strony (np. brak migracji na świeżej bazie)
        return {}
    return {"nav_active_count": active, "nav_due_count": due, "nav_balance": balance, "nav_limit": limit}
