"""Deleting finished jobs: their files on disk and their database rows."""
import shutil

from .models import Job


def dir_size(path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def purge_job(job) -> int:
    """Delete one finished job (files + row). Returns bytes freed. Refuses active jobs:
    their compute machine still writes into the job and must be stopped first."""
    if job.is_active:
        raise ValueError(f"{job.public_id} is still active ({job.status})")
    size = dir_size(job.dir)
    shutil.rmtree(job.dir, ignore_errors=True)
    job.delete()
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
