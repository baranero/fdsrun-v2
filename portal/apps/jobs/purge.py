"""Deleting finished jobs: their files on disk and their database rows."""
import shutil

from .models import Job


def dir_size(path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def purge_job(job) -> int:
    """Admin: delete one finished job for good (files + row; its machine's cost record stays).
    Returns bytes freed. Refuses active jobs: their machine still writes into the job."""
    if job.is_active:
        raise ValueError(f"{job.public_id} is still active ({job.status})")
    from apps.compute.models import Machine

    if Machine.objects.filter(job=job).exclude(status=Machine.Status.DELETED).exists():
        raise ValueError(f"{job.public_id}: its machine is not deleted yet")
    Machine.objects.filter(job=job).update(job_ref=f"{job.public_id} {job.owner.email}"[:80])
    size = dir_size(job.dir)
    shutil.rmtree(job.dir, ignore_errors=True)
    job.delete()
    return size


def hide_job(job) -> int:
    """Client: delete all files of a finished job and hide it from their lists. The row stays
    (price, times, owner) because it is the basis of the invoice."""
    from django.utils import timezone

    if job.is_active:
        raise ValueError(f"{job.public_id} is still active ({job.status})")
    size = dir_size(job.dir)
    shutil.rmtree(job.dir, ignore_errors=True)
    job.hidden_at = timezone.now()
    job.save(update_fields=["hidden_at"])
    return size


def purge_files(job) -> int:
    """Delete only the result files and archives; the job stays in the history."""
    if job.is_active:
        raise ValueError(f"{job.public_id} is still active ({job.status})")
    size = 0
    for d in (job.results_dir, job.dir / "archives"):
        size += dir_size(d)
        shutil.rmtree(d, ignore_errors=True)
    return size


__all__ = ["purge_job", "purge_files", "dir_size", "Job"]
