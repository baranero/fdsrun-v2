"""Continue an interrupted job from FDS restart files instead of computing from zero."""
import shutil

from django.utils import timezone

from .analyzer import make_restart_input, prepare_run_file
from .models import Job, log_event

RESUMABLE = (Job.Status.STALLED, Job.Status.CANCELLED, Job.Status.FAILED)


def restart_files(job):
    if not job.results_dir.exists():
        return []
    return sorted(p for p in job.results_dir.iterdir() if p.is_file() and p.name.endswith(".restart"))


def resumable(job) -> bool:
    return job.status in RESUMABLE and bool(restart_files(job)) and not job.restarts.exists()


def resume(job, actor) -> Job:
    """New job that continues `job`: same model and server, RESTART=.TRUE., and the old job's
    result files MOVED (not copied) into it — FDS appends to them, the disk holds one copy."""
    if not resumable(job):
        raise ValueError("Tego zlecenia nie da się wznowić (brak plików restartu albo już wznowione).")
    new = Job(owner=job.owner, name=f"{job.name} (wznowienie)"[:120], project=job.project, note=job.note,
              filename=job.filename, chid=job.chid, analysis=job.analysis, total_cells=job.total_cells,
              n_meshes=job.n_meshes, sim_time=job.sim_time, procs=job.procs, server_type=job.server_type,
              restart_of=job)
    left = max(0.05, 1 - (job.progress_t or 0) / job.sim_time) if job.sim_time else 1
    new.est_hours = job.est_hours * left
    new.est_cost_eur = job.est_cost_eur * left
    new.est_price_pln = job.est_price_pln * left
    new.save()
    new.input_path.parent.mkdir(parents=True, exist_ok=True)
    make_restart_input(job.input_path, new.input_path)
    new.results_dir.mkdir(parents=True, exist_ok=True)
    for p in job.results_dir.iterdir():
        if p.is_file() and p.name != "fds_stdout.log":
            shutil.move(str(p), new.results_dir / p.name)
    shutil.rmtree(job.dir / "archives", ignore_errors=True)
    prepare_run_file(new.input_path, new.run_path, new.procs)
    log_event(job, "resumed", f"wyniki przeniesione do {new.public_id}", actor=actor)
    log_event(new, "resume_of", f"{job.public_id} od t ≈ {job.progress_t:.0f} s", actor=actor)
    new.started_at = timezone.now()
    new.set_status(Job.Status.QUEUED, f"Wznowienie {job.public_id} od ostatniego zapisu restartu")
    return new
