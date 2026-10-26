"""Create a tiny job from the bundled fixture and start it on a real compute machine.
Costs about 0.01 EUR; proves the whole chain portal -> Hetzner -> FDS -> results."""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.compute import tasks
from apps.jobs.analyzer import analyze_file
from apps.jobs.models import Job, log_event
from apps.jobs.views import _apply_analysis

FIXTURE = Path(settings.BASE_DIR) / "apps" / "jobs" / "fixtures" / "minimal.fds"


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--server", default="cpx32")

    def handle(self, *args, **opts):
        user, _ = User.objects.get_or_create(email="smoke@fdsrun.internal", defaults={"kind": "company"})
        job = Job(owner=user, name="smoke-test", filename="minimal.fds")
        job.save()
        job.input_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURE, job.input_path)
        _apply_analysis(job, analyze_file(job.input_path))
        opt = next(o for o in job.analysis["advice"]["options"] if o["server"] == opts["server"])
        job.procs, job.server_type = opt["procs"], opt["server"]
        job.est_hours, job.est_cost_eur, job.est_price_pln = opt["hours"], opt["costEur"], opt["pricePln"]
        job.set_status(Job.Status.QUEUED, "smoke test")
        log_event(job, "start", "smoke test", actor="system")
        tasks.launch_job.delay(job.id)
        self.stdout.write(job.public_id)
