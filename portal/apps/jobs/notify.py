"""Outgoing mail: job finished / failed, and alerts for the admin. Never raises."""

import logging

from django.conf import settings
from django.core.mail import send_mail

log = logging.getLogger(__name__)

SUBJECTS = {
    "done": "Obliczenia zakończone: {name}",
    "failed": "Obliczenia przerwane błędem: {name}",
    "stalled": "Maszyna przestała odpowiadać: {name}",
    "cancelled": "Obliczenia zatrzymane: {name}",
}


def _send(to, subject, body):
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
    except Exception:  # noqa: BLE001
        log.exception("mail to %s failed: %s", to, subject)


def job_finished(job):
    subject = SUBJECTS.get(job.status)
    if not subject:
        return
    url = f"{settings.PORTAL_URL}/zlecenia/{job.public_id}/"
    lines = [
        f"Zlecenie {job.public_id} — {job.name}",
        f"Status: {job.get_status_display()}",
    ]
    if job.status_message:
        lines.append(f"Szczegóły: {job.status_message}")
    if job.wall_seconds:
        lines.append(f"Czas liczenia: {job.wall_seconds / 3600:.1f} h")
    if job.price_pln or job.est_price_pln:
        lines.append(f"Cena netto: {job.price_pln or job.est_price_pln:.0f} zł")
    lines += ["", f"Wyniki i log: {url}", "", "fdsrun"]
    _send(job.owner.email, subject.format(name=job.name), "\n".join(lines))


def admin_alert(subject, body):
    _send(settings.ADMIN_EMAIL, f"[fdsrun {settings.ENVIRONMENT}] {subject}", body)
