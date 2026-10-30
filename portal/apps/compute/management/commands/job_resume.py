from django.core.management.base import BaseCommand

from apps.compute import tasks
from apps.jobs.models import Job
from apps.jobs.resume import resume


class Command(BaseCommand):
    help = "Continue an interrupted job from its FDS restart files (same as the user's button)."

    def add_arguments(self, parser):
        parser.add_argument("public_id")

    def handle(self, *args, **opts):
        job = Job.objects.get(public_id=opts["public_id"])
        new = resume(job, "admin-cli")
        tasks.launch_job.delay(new.id)
        self.stdout.write(f"resumed as {new.public_id}: {new.procs} proc, {new.server_type}, est {new.est_hours:.1f} h, {len(list(new.results_dir.iterdir()))} files moved")
