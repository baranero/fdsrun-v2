from django.core.management.base import BaseCommand

from apps.jobs.archives import build_archives
from apps.jobs.models import Job, log_event


class Command(BaseCommand):
    help = "Build (or rebuild) the result archives of a finished job."

    def add_arguments(self, parser):
        parser.add_argument("public_id")

    def handle(self, *args, **opts):
        job = Job.objects.get(public_id=opts["public_id"])
        n = build_archives(job)
        log_event(job, "archives", f"{n} archiwa gotowe (ręcznie)", actor="admin-cli")
        self.stdout.write(f"{n} archives")
