from django.db import models
from django.utils import timezone

from apps.jobs.models import Job

# Hourly prices (EUR, net) used for cost bookkeeping until live prices are pulled from the API.
SERVER_TYPES = {
    "cpx32": {"vcpu": 4, "eur_per_hour": 0.055},
    "cpx42": {"vcpu": 8, "eur_per_hour": 0.111},
    "cpx62": {"vcpu": 16, "eur_per_hour": 0.208},
}


class Machine(models.Model):
    """A Hetzner Cloud server created for one job. Deleted as soon as the job ends."""

    class Status(models.TextChoices):
        CREATING = "creating", "Tworzona"
        RUNNING = "running", "Działa"
        DELETING = "deleting", "Usuwana"
        DELETED = "deleted", "Usunięta"
        LOST = "lost", "Nie udało się usunąć"

    job = models.OneToOneField(Job, on_delete=models.PROTECT, related_name="machine")
    hcloud_id = models.BigIntegerField(null=True, blank=True, unique=True)
    name = models.CharField(max_length=64)
    server_type = models.CharField(max_length=12)
    location = models.CharField(max_length=12)
    ip = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATING)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    eur_per_hour = models.FloatField(default=0)
    error = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} ({self.status})"

    @property
    def hours(self) -> float:
        end = self.deleted_at or timezone.now()
        # Hetzner bills started hours
        return max(1 / 60, (end - self.created_at).total_seconds() / 3600)

    @property
    def cost_eur(self) -> float:
        return round(self.hours * self.eur_per_hour, 4)
