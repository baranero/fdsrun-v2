"""Result archives and download links.

After a job ends, its result files are packed into three uncompressed ZIPs (CSV + logs,
Smokeview, everything) so that a user downloads one file instead of hundreds. Downloads go
through /pobierz/<id>/<name>: in production Caddy serves the bytes (with HTTP Range, so
curl -C - / wget -c resume), after asking Django whether the request may see the file.
"""
import hashlib
import time
import zipfile
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils.crypto import constant_time_compare, salted_hmac
from django.urls import reverse
from django.utils import timezone

LINK_MAX_AGE = 7 * 24 * 3600  # signed links are valid for a week
SIGNER_SALT = "fdsrun.download"

# (key, title, description, extensions). "csv" and "logs" together form the small archive.
FILE_GROUPS = (
    ("csv", "Wyniki CSV", "Wykresy, czujniki, HRR, bilans masy", (".csv",)),
    ("smokeview", "Smokeview", "Pliki do wizualizacji w Smokeview", (".smv", ".sf", ".bf", ".q", ".s3d", ".iso", ".prt5", ".sz", ".ge", ".xyz", ".bnd", ".sinfo", ".binfo")),
    ("logs", "Dzienniki", "Log FDS i wyjście programu", (".out", ".log", ".end", ".notready", ".stop")),
    ("input", "Plik wejściowy", "", (".fds",)),
)

ARCHIVES = (
    ("csv", "CSV i logi", "Wykresy, czujniki, log FDS; zwykle wszystko, czego potrzebuje raport", ("csv", "logs", "input")),
    ("smokeview", "Smokeview", "Pliki do wizualizacji; duże", ("smokeview", "input")),
    ("all", "Wszystko", "Komplet wyników", None),
)


DESCRIPTIONS = (
    ("_hrr.csv", "Krzywa mocy pożaru (HRR) i bilans energii"),
    ("_devc.csv", "Odczyty czujników (DEVC)"),
    ("_ctrl.csv", "Stany sterowników (CTRL)"),
    ("_mass.csv", "Bilans masy gatunków"),
    ("_steps.csv", "Krok czasowy i CFL w czasie"),
    ("_cpu.csv", "Czas procesora na proces MPI"),
    ("_evac.csv", "Wyniki ewakuacji"),
    (".smv", "Główny plik projektu Smokeview"),
    (".sf", "Przekrój (slice) — otwórz w Smokeview"),
    (".bf", "Dane na powierzchniach (boundary)"),
    (".s3d", "Dym i widoczność 3D"),
    (".iso", "Izopowierzchnie"),
    (".prt5", "Cząstki"),
    (".q", "Pole 3D (plot3d)"),
    (".out", "Główny log FDS: kroki, ostrzeżenia, błędy"),
    ("fds_stdout.log", "Wyjście programu i MPI (diagnostyka)"),
    (".fds", "Plik wejściowy, który policzono"),
    (".end", "Znacznik zakończenia biegu"),
    ("_git.txt", "Wersja FDS"),
)


def describe(name: str) -> str:
    low = name.lower()
    return next((d for suffix, d in DESCRIPTIONS if low.endswith(suffix)), "")


def group_of(name: str) -> str:
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    return next((g[0] for g in FILE_GROUPS if ext in g[3]), "other")


def group_files(files):
    """files = Job.result_files(); returns the groups that are non-empty, in FILE_GROUPS order."""
    groups = {g[0]: {"key": g[0], "title": g[1], "desc": g[2], "files": [], "size": 0} for g in FILE_GROUPS}
    groups["other"] = {"key": "other", "title": "Inne", "desc": "", "files": [], "size": 0}
    for f in files:
        g = groups[group_of(f["name"])]
        f = dict(f, desc=describe(f["name"]))
        g["files"].append(f)
        g["size"] += f["size"]
    return [g for g in groups.values() if g["files"]]


def archive_dir(job) -> Path:
    return job.dir / "archives"


def archive_name(job, key) -> str:
    return f"{job.chid or job.public_id}_{key}.zip"


def archive_files(job):
    """Archives that exist, with sizes: [{key, title, desc, name, size, sha256}]."""
    d = archive_dir(job)
    if not (d / "ready").exists():
        return []
    out = []
    for key, title, desc, _ in ARCHIVES:
        p = d / archive_name(job, key)
        if p.is_file():
            sha = (d / (p.name + ".sha256")).read_text().split()[0] if (d / (p.name + ".sha256")).exists() else ""
            out.append({"key": key, "title": title, "desc": desc, "name": p.name, "size": p.stat().st_size, "sha256": sha,
                        "built": timezone.datetime.fromtimestamp((d / "ready").stat().st_mtime, tz=timezone.get_current_timezone())})
    return out


def archives_building(job) -> bool:
    """True while archives are being packed; a marker older than 2 h is treated as stale."""
    d = archive_dir(job)
    marker = d / "building"
    if not marker.exists() or (d / "ready").exists():
        return False
    import time

    return time.time() - marker.stat().st_mtime < 7200


def build_archives(job) -> int:
    """Pack result files into the three ZIPs (stored, not deflated: FDS output does not compress
    well and storing is many times faster). Returns the number of archives written."""
    files = [p for p in job.results_dir.iterdir() if p.is_file()] if job.results_dir.exists() else []
    if not files:
        return 0
    d = archive_dir(job)
    d.mkdir(parents=True, exist_ok=True)
    (d / "ready").unlink(missing_ok=True)
    (d / "building").write_text("1\n")
    n = 0
    for key, _, _, groups in ARCHIVES:
        chosen = [p for p in files if groups is None or group_of(p.name) in groups]
        # a partial archive only makes sense when it holds something of its own kind
        if not chosen or (key == "smokeview" and not any(group_of(p.name) == "smokeview" for p in chosen)) or (key == "csv" and not any(group_of(p.name) in ("csv", "logs") for p in chosen)):
            continue
        target = d / archive_name(job, key)
        tmp = d / (target.name + ".part")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for p in sorted(chosen):
                z.write(p, arcname=p.name)
        tmp.replace(target)
        h = hashlib.sha256()
        with open(target, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        (d / (target.name + ".sha256")).write_text(f"{h.hexdigest()}  {target.name}\n")
        n += 1
    (d / "ready").write_text("ok\n")
    (d / "building").unlink(missing_ok=True)
    return n


@shared_task
def build_archives_task(job_id):
    from .models import Job, log_event

    job = Job.objects.get(id=job_id)
    try:
        n = build_archives(job)
    finally:
        (archive_dir(job) / "building").unlink(missing_ok=True)
    if n:
        log_event(job, "archives", f"{n} archiwa gotowe" + (" (stan w trakcie obliczeń)" if job.is_active else ""), actor="system")


# ----- download links -----

def resolve(job, name):
    """Map a download name to (path on disk, relative path under JOB_DATA_ROOT) or None."""
    for base in (archive_dir(job), job.results_dir):
        p = (base / name).resolve()
        if str(p).startswith(str(base.resolve())) and p.is_file() and not p.name.endswith(".part") and p.name != "ready":
            rel = p.relative_to(Path(settings.JOB_DATA_ROOT).resolve())
            return p, "/" + rel.as_posix()
    if name == job.filename and job.input_path.is_file():
        return job.input_path, "/" + job.input_path.resolve().relative_to(Path(settings.JOB_DATA_ROOT).resolve()).as_posix()
    return None


def _sig(job, name, exp) -> str:
    return salted_hmac(SIGNER_SALT, f"{job.public_id}:{name}:{exp}").hexdigest()[:32]


def make_token(job, name) -> str:
    """Short token: <expiry unix time>-<hmac>; the link stays readable."""
    exp = int(time.time()) + LINK_MAX_AGE
    return f"{exp}-{_sig(job, name, exp)}"


def check_token(token, job, name) -> bool:
    try:
        exp_s, sig = token.split("-", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    return exp > time.time() and constant_time_compare(sig, _sig(job, name, exp))


def download_url(job, name, request=None, signed=False) -> str:
    url = reverse("download", args=[job.public_id, name])
    if signed:
        url += "?t=" + make_token(job, name)
    return request.build_absolute_uri(url) if request else url
