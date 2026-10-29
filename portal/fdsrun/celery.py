import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fdsrun.settings")

app = Celery("fdsrun")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Periodic housekeeping: stalled jobs, forgotten machines.
from celery.schedules import crontab  # noqa: E402

app.conf.beat_schedule = {
    "monthly-invoices": {"task": "apps.billing.tasks.monthly_invoices", "schedule": crontab(day_of_month=1, hour=6, minute=7)},
    "overdue-reminders": {"task": "apps.billing.tasks.overdue_reminders", "schedule": crontab(hour=9, minute=13)},
    "watchdog-every-minute": {"task": "apps.compute.tasks.watchdog", "schedule": 60.0},
    "housekeeping-hourly": {"task": "apps.compute.tasks.housekeeping", "schedule": 3600.0},
}
