from celery import shared_task

from . import services


@shared_task
def invoice_job(job_id):
    from apps.jobs.models import Job

    job = Job.objects.select_related("owner").get(id=job_id)
    services.invoice_finished_job(job)


@shared_task
def monthly_invoices():
    return len(services.monthly_run())


@shared_task
def overdue_reminders():
    return services.remind_overdue()
