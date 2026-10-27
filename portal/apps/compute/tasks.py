import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.jobs import notify
from apps.jobs.models import Job, log_event

from . import hcloud_client
from .models import SERVER_TYPES, Machine, ServerCalibration

log = logging.getLogger(__name__)

FINAL = {Job.Status.DONE, Job.Status.FAILED, Job.Status.CANCELLED, Job.Status.STALLED}


@shared_task(bind=True, max_retries=3)
def launch_job(self, job_id):
    job = Job.objects.get(id=job_id)
    if job.status != Job.Status.QUEUED:
        return
    job.set_status(Job.Status.PROVISIONING, "Tworzę maszynę obliczeniową")
    name = f"{settings.COMPUTE_LABEL}-{job.public_id.lower()}"
    machine, _ = Machine.objects.get_or_create(
        job=job,
        defaults={"name": name, "server_type": job.server_type, "location": settings.HCLOUD_LOCATION,
                  "eur_per_hour": SERVER_TYPES.get(job.server_type, {}).get("eur_per_hour", 0)},
    )
    try:
        hid, ip = hcloud_client.create_server(job, name, job.server_type)
    except Exception as e:  # noqa: BLE001
        log.exception("server creation failed for %s", job.public_id)
        machine.error = str(e)[:2000]
        machine.save()
        if self.request.retries < self.max_retries:
            job.status_message = f"Chmura nie dała maszyny, ponawiam ({self.request.retries + 1}/3)"
            job.save(update_fields=["status_message"])
            raise self.retry(countdown=60 * (self.request.retries + 1))
        job.set_status(Job.Status.FAILED, f"Nie udało się utworzyć maszyny: {e}")
        log_event(job, "provision_failed", str(e))
        return
    machine.hcloud_id, machine.ip, machine.status = hid, ip, Machine.Status.RUNNING
    machine.created_at = timezone.now()
    machine.save()
    job.last_heartbeat = timezone.now()
    job.set_status(Job.Status.PROVISIONING, "Maszyna startuje, instaluję FDS")
    log_event(job, "machine_created", f"{name} {job.server_type} {ip}")


@shared_task
def stop_job(job_id):
    """User asked to stop: the agent sees stop_requested on its next heartbeat and
    uploads what it has. If it does not confirm within 3 minutes, we pull the plug."""
    job = Job.objects.get(id=job_id)
    if job.status in FINAL:
        return
    if job.status in (Job.Status.QUEUED, Job.Status.PROVISIONING):
        finish_job.delay(job.id, Job.Status.CANCELLED, "Przerwane przed startem")
    else:
        finish_job.apply_async((job.id, Job.Status.CANCELLED, "Przerwane przez użytkownika"), countdown=180)


@shared_task
def finish_job(job_id, status, message=""):
    """Close the job and delete its machine. Idempotent: safe to call twice."""
    with transaction.atomic():
        job = Job.objects.select_for_update().get(id=job_id)
        if job.status in FINAL:
            return
        job.set_status(status, message)
        log_event(job, "finished", f"{status}: {message}", actor="agent" if status == Job.Status.DONE else "system")
    if status == Job.Status.DONE:
        recalibrate(job)
    from apps.jobs.archives import build_archives_task

    build_archives_task.delay(job.id)
    notify.job_finished(job)
    if status == Job.Status.STALLED:
        notify.admin_alert(f"zlecenie {job.public_id} bez odpowiedzi", f"{job.owner.email}, {job.name}, {job.server_type}: {message}")
    delete_machine.delay(job.id)


def recalibrate(job):
    """Feed the measured speed of this run back into the estimator."""
    max_load = (job.analysis.get("model") or {}).get("maxLoad") or 0
    if job.progress_step > 1000 and job.wall_seconds > 300 and max_load:
        k = job.wall_seconds / (max_load * job.progress_step)
        row = ServerCalibration.record(job.server_type, k)
        if row:
            log_event(job, "calibration", f"k={k:.3g} s/cell-step on {job.server_type}; running value {row.k:.3g} ({row.samples} samples)")


@shared_task(bind=True, max_retries=10)
def delete_machine(self, job_id):
    try:
        machine = Machine.objects.get(job_id=job_id)
    except Machine.DoesNotExist:
        return
    if machine.status in (Machine.Status.DELETED,):
        return
    if machine.hcloud_id is None:
        machine.status = Machine.Status.DELETED
        machine.deleted_at = timezone.now()
        machine.save()
        return
    machine.status = Machine.Status.DELETING
    machine.save(update_fields=["status"])
    try:
        hcloud_client.delete_server(machine.hcloud_id)
    except Exception as e:  # noqa: BLE001
        machine.error = str(e)[:2000]
        machine.save(update_fields=["error"])
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=120)
        machine.status = Machine.Status.LOST
        machine.save(update_fields=["status"])
        log_event(machine.job, "machine_lost", str(e))
        notify.admin_alert(f"nie mogę usunąć maszyny {machine.name}", f"Hetzner id {machine.hcloud_id}, {machine.server_type}, ip {machine.ip}. Błąd: {e}\nUsuń ją ręcznie w konsoli Hetzner — nalicza koszty.")
        return
    machine.status = Machine.Status.DELETED
    machine.deleted_at = timezone.now()
    machine.save()
    job = machine.job
    from apps.jobs.analyzer import multiplier_for

    job.cost_eur = machine.cost_eur
    # client price = actual server cost × multiplier for the account type (decisions 5-6)
    job.price_pln = round(machine.cost_eur * settings.PRICING["eur_pln"] * multiplier_for(job.owner), 2)
    job.save(update_fields=["cost_eur", "price_pln"])
    log_event(job, "machine_deleted", f"{machine.hours:.2f} h, {machine.cost_eur:.3f} EUR")


@shared_task
def watchdog():
    """Runs every minute: stalled jobs lose their machine; machines without a live job are deleted."""
    now = timezone.now()
    timeout = timezone.timedelta(seconds=settings.COMPUTE_HEARTBEAT_TIMEOUT_S)
    for job in Job.objects.filter(status__in=[Job.Status.PROVISIONING, Job.Status.TESTING, Job.Status.RUNNING, Job.Status.FINISHING]):
        last = job.last_heartbeat or job.started_at or job.created_at
        limit = timeout * (3 if job.status == Job.Status.PROVISIONING else 1)
        if now - last > limit:
            finish_job.delay(job.id, Job.Status.STALLED, "Maszyna przestała odpowiadać; wyniki do ostatniego zapisu są dostępne")
    # retry machines that failed to delete
    for m in Machine.objects.filter(status=Machine.Status.LOST):
        delete_machine.delay(m.job_id)
    # forgotten machines in the cloud (no row, or row already deleted)
    if not settings.HCLOUD_TOKEN:
        return
    try:
        servers = hcloud_client.list_app_servers()
    except Exception:  # noqa: BLE001
        log.exception("watchdog: cannot list servers")
        return
    known = set(Machine.objects.exclude(status=Machine.Status.DELETED).values_list("hcloud_id", flat=True))
    for s in servers:
        if s.id not in known:
            log.warning("watchdog: deleting forgotten server %s %s", s.id, s.name)
            try:
                s.delete()
                notify.admin_alert(f"usunąłem zapomnianą maszynę {s.name}", f"Serwer {s.id} ({s.server_type.name}) nie był przypisany do żadnego żywego zlecenia; watchdog go usunął.")
            except Exception as e:  # noqa: BLE001
                log.exception("watchdog: delete failed for %s", s.id)
                notify.admin_alert(f"zapomniana maszyna {s.name} — nie mogę usunąć", f"Serwer {s.id}: {e}. Usuń ręcznie w konsoli Hetzner.")
