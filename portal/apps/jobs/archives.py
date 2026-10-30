"""Result archives and download links.

After a job ends, the small "CSV and logs" ZIP is packed automatically. The large ones
(Smokeview, everything) duplicate gigabytes of results, so they are packed only when the user
asks, only if the disk has room, and are deleted again after LARGE_ARCHIVE_HOURS (the result
files themselves stay). See the 30.10.2026 incident: duplicated archives filled the disk. Downloads go
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
AUTO_ARCHIVES = ("csv",)
LARGE_ARCHIVE_HOURS = 48
DISK_RESERVE_BYTES = 5 * 1024**3   # never let an archive eat the last 5 GB


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


def _chosen(job, key, files):
    groups = next(g for k, _, _, g in ARCHIVES if k == key)
    chosen = [p for p in files if groups is None or group_of(p.name) in groups]
    if key == "smokeview" and not any(group_of(p.name) == "smokeview" for p in chosen):
        return []
    if key == "csv" and not any(group_of(p.name) in ("csv", "logs") for p in chosen):
        return []
    return chosen


def archive_files(job):
    """Every archive kind with its state: [{key, title, desc, name, ready, building, size, est_size, built, sha256}].
    `size` only for ready ones; `est_size` is what packing would take."""
    d = archive_dir(job)
    files = [p for p in job.results_dir.iterdir() if p.is_file()] if job.results_dir.exists() else []
    out = []
    for key, title, desc, _ in ARCHIVES:
        chosen = _chosen(job, key, files)
        if not chosen:
            continue
        p = d / archive_name(job, key)
        ready = p.is_file()
        marker = d / f"building-{key}"
        building = marker.exists() and not ready and time.time() - marker.stat().st_mtime < 7200
        item = {"key": key, "title": title, "desc": desc, "name": p.name, "ready": ready, "building": building,
                "large": key not in AUTO_ARCHIVES, "est_size": sum(f.stat().st_size for f in chosen)}
        if ready:
            st = p.stat()
            sha = d / (p.name + ".sha256")
            item.update(size=st.st_size, sha256=sha.read_text().split()[0] if sha.exists() else "",
                        built=timezone.datetime.fromtimestamp(st.st_mtime, tz=timezone.get_current_timezone()))
            if key not in AUTO_ARCHIVES:
                item["expires"] = item["built"] + timezone.timedelta(hours=LARGE_ARCHIVE_HOURS)
        out.append(item)
    return out


def ready_archives(job):
    return [a for a in archive_files(job) if a["ready"]]


def archives_building(job) -> bool:
    return any(a["building"] for a in archive_files(job))


def room_for(nbytes) -> bool:
    import shutil

    root = Path(settings.JOB_DATA_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(root).free - nbytes > DISK_RESERVE_BYTES


def build_archives(job, keys=AUTO_ARCHIVES) -> int:
    """Pack the given archive kinds (stored, not deflated: FDS output does not compress well and
    storing is many times faster). Skips a kind when the disk has no room. Returns the number written."""
    files = [p for p in job.results_dir.iterdir() if p.is_file()] if job.results_dir.exists() else []
    if not files:
        return 0
    d = archive_dir(job)
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for key in keys:
        chosen = _chosen(job, key, files)
        if not chosen:
            continue
        marker = d / f"building-{key}"
        if not room_for(sum(p.stat().st_size for p in chosen)):
            marker.unlink(missing_ok=True)
            continue
        marker.write_text("1\n")
        target = d / archive_name(job, key)
        tmp = d / (target.name + ".part")
        try:
            target.unlink(missing_ok=True)
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
        except OSError:
            tmp.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
        finally:
            marker.unlink(missing_ok=True)
    return n


def expire_large_archives(now=None) -> int:
    """Delete on-demand archives older than LARGE_ARCHIVE_HOURS. Returns bytes freed."""
    now = now or time.time()
    freed = 0
    root = Path(settings.JOB_DATA_ROOT)
    if not root.exists():
        return 0
    for d in root.glob("*/archives"):
        for p in d.iterdir():
            if p.is_file() and not any(p.name.endswith(f"_{k}.zip") or p.name.endswith(f"_{k}.zip.sha256") for k in AUTO_ARCHIVES) \
                    and p.name.endswith((".zip", ".sha256")) and now - p.stat().st_mtime > LARGE_ARCHIVE_HOURS * 3600:
                freed += p.stat().st_size
                p.unlink()
    return freed


@shared_task
def build_archives_task(job_id, keys=AUTO_ARCHIVES):
    from .models import Job, log_event

    job = Job.objects.get(id=job_id)
    n = build_archives(job, tuple(keys))
    if n:
        log_event(job, "archives", f"gotowe: {', '.join(keys)}" + (" (stan w trakcie obliczeń)" if job.is_active else ""), actor="system")
    elif any(k not in AUTO_ARCHIVES for k in keys):
        log_event(job, "archives_skipped", "za mało miejsca na dysku na duże archiwum", actor="system")


# ----- download links -----

def resolve(job, name):
    """Map a download name to (path on disk, relative path under JOB_DATA_ROOT) or None."""
    for base in (archive_dir(job), job.results_dir):
        p = (base / name).resolve()
        if str(p).startswith(str(base.resolve())) and p.is_file() and not p.name.endswith(".part") and p.name != "ready" and not p.name.startswith("building"):
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
