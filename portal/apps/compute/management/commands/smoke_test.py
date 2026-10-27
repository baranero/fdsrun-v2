"""Create a tiny job from the bundled fixture and start it on a real compute machine.
Costs about 0.01 EUR; proves the whole chain portal -> Hetzner -> FDS -> results."""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.compute import tasks
from apps.jobs.analyzer import analyze_file, prepare_run_file
from apps.jobs.models import Job, log_event
from apps.jobs.views import _apply_analysis

FIXTURE = Path(settings.BASE_DIR) / "apps" / "jobs" / "fixtures" / "minimal.fds"


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--server", default="cpx32")
        parser.add_argument("--copy-of", default="", help="public id of an existing job whose input file to rerun")
        parser.add_argument("--procs", type=int, default=0)

    def handle(self, *args, **opts):
        user, _ = User.objects.get_or_create(email="smoke@fdsrun.internal", defaults={"kind": "company"})
        src, name = FIXTURE, "minimal.fds"
        if opts["copy_of"]:
            orig = Job.objects.get(public_id=opts["copy_of"])
            src, name = orig.input_path, orig.filename
        job = Job(owner=user, name=f"smoke-test {name}", filename=name)
        job.save()
        job.input_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, job.input_path)
        _apply_analysis(job, analyze_file(job.input_path))
        opts_for_server = [o for o in job.analysis["advice"]["options"] if o["server"] == opts["server"]]
        opt = next((o for o in opts_for_server if o["procs"] == opts["procs"]), None) or min(opts_for_server, key=lambda o: o["hours"])
        job.procs, job.server_type = opt["procs"], opt["server"]
        job.est_hours, job.est_cost_eur, job.est_price_pln = opt["hours"], opt["costEur"], opt["pricePln"]
        prepare_run_file(job.input_path, job.run_path, job.procs)
        job.set_status(Job.Status.QUEUED, "smoke test")
        log_event(job, "start", "smoke test", actor="system")
        tasks.launch_job.delay(job.id)
        self.stdout.write(job.public_id)
