import shutil

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.compute import tasks
from apps.jobs.analyzer import analyze_file, multiplier_for, prepare_run_file
from apps.jobs.views import _apply_analysis
from apps.jobs.models import Job, log_event


class Command(BaseCommand):
    help = "Relaunch a finished/failed job as a new job of the same owner with the same input and variant."

    def add_arguments(self, parser):
        parser.add_argument("public_id")

    def handle(self, *args, **opts):
        orig = Job.objects.get(public_id=opts["public_id"])
        if orig.is_active:
            raise CommandError("job is still active")
        job = Job(owner=orig.owner, name=orig.name, filename=orig.filename)
        job.save()
        job.input_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(orig.input_path, job.input_path)
        _apply_analysis(job, analyze_file(job.input_path, multiplier_for(orig.owner)))
        opt = next((o for o in job.analysis["advice"]["options"] if o["procs"] == orig.procs and o["server"] == orig.server_type), None)
        if opt is None:
            opt = min(job.analysis["advice"]["options"], key=lambda o: o["hours"])
        job.procs, job.server_type = opt["procs"], opt["server"]
        job.est_hours, job.est_cost_eur, job.est_price_pln = opt["hours"], opt["costEur"], opt["pricePln"]
        info = prepare_run_file(job.input_path, job.run_path, job.procs)
        log_event(job, "run_file", f"MPI_PROCESS assigned for {info['procs']} processes, busiest {info['maxLoad']} cells", actor="system")
        job.started_at = timezone.now()
        job.set_status(Job.Status.QUEUED, "Czeka na maszynę")
        log_event(job, "start", f"retry of {orig.public_id}: {job.procs} proc, {job.server_type}, est {job.est_hours:.1f} h", actor="admin-cli")
        tasks.launch_job.delay(job.id)
        self.stdout.write(f"new job {job.public_id}: {job.procs} proc, {job.server_type}, est {job.est_hours:.1f} h")
