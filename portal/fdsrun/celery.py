import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fdsrun.settings")

app = Celery("fdsrun")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Periodic housekeeping: stalled jobs, forgotten machines.
app.conf.beat_schedule = {
    "watchdog-every-minute": {"task": "apps.compute.tasks.watchdog", "schedule": 60.0},
    "housekeeping-hourly": {"task": "apps.compute.tasks.housekeeping", "schedule": 3600.0},
}
