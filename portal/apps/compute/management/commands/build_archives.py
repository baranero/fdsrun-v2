from django.core.management.base import BaseCommand

from apps.jobs.archives import build_archives
from apps.jobs.models import Job, log_event


class Command(BaseCommand):
    help = "Build (or rebuild) the result archives of a finished job."

    def add_arguments(self, parser):
        parser.add_argument("public_id", nargs="?")
        parser.add_argument("--all-done", action="store_true", help="the CSV archive for every finished job that lacks it")
        parser.add_argument("--keys", default="csv", help="comma-separated: csv,smokeview,all")

    def handle(self, *args, **opts):
        keys = tuple(k for k in opts["keys"].split(",") if k)
        jobs = Job.objects.exclude(status__in=Job.ACTIVE) if opts["all_done"] else Job.objects.filter(public_id=opts["public_id"])
        for job in jobs:
            n = build_archives(job, keys)
            if n:
                log_event(job, "archives", f"gotowe: {', '.join(keys)} (ręcznie)", actor="admin-cli")
            self.stdout.write(f"{job.public_id}: {n} archives")
