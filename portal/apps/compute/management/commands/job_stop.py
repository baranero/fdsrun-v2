from django.core.management.base import BaseCommand

from apps.compute import tasks
from apps.jobs.models import Job, log_event


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("public_id")

    def handle(self, *args, **opts):
        job = Job.objects.get(public_id=opts["public_id"])
        if job.is_active:
            job.stop_requested = True
            job.save(update_fields=["stop_requested"])
            log_event(job, "stop_requested", actor="admin-cli")
            tasks.stop_job.delay(job.id)
            self.stdout.write("stop requested")
        else:
            self.stdout.write(f"job is {job.status}")
