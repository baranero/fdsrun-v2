"""HTTP API used by the agent running on the compute machine.

Every request carries `Authorization: Bearer <job.agent_token>`; the token is
unique per job and known only to that machine (it travels in cloud-init).
"""

import json
import re
from functools import wraps
from pathlib import Path

from django.http import FileResponse, HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.jobs.models import Job, log_event

from . import tasks

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,200}$")
TEST_WINDOW_S = 120


def agent_auth(view):
    @wraps(view)
    def wrapper(request, public_id, *args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return HttpResponseForbidden("missing token")
        try:
            job = Job.objects.get(public_id=public_id)
        except Job.DoesNotExist:
            return HttpResponseForbidden("unknown job")
        if auth[7:] != job.agent_token:
            return HttpResponseForbidden("bad token")
        return view(request, job, *args, **kwargs)

    return csrf_exempt(wrapper)


@require_GET
@agent_auth
def job_spec(request, job):
    return JsonResponse({
        "job_id": job.public_id,
        "filename": job.filename,
        "chid": job.chid,
        "procs": job.procs,
        "fds_version": job.fds_version,
        "sim_time": job.sim_time,
        "test_window_s": TEST_WINDOW_S,
    })


@require_GET
@agent_auth
def job_input(request, job):
    return FileResponse(open(job.input_path, "rb"), as_attachment=True, filename=job.filename)


@require_POST
@agent_auth
def job_progress(request, job):
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponse("bad json", status=400)
    if job.status in tasks.FINAL:
        return JsonResponse({"action": "stop"})
    job.last_heartbeat = timezone.now()
    phase = data.get("phase", "")
    if phase == "preparing" and job.status == Job.Status.PROVISIONING:
        job.status, job.status_message = Job.Status.PROVISIONING, data.get("message", "Przygotowuję maszynę")
    elif phase == "running":
        job.progress_step = int(data.get("step", job.progress_step))
        job.progress_t = float(data.get("t", job.progress_t))
        job.progress_dt = float(data.get("dt", job.progress_dt))
        job.wall_seconds = float(data.get("wall_s", job.wall_seconds))
        if job.status in (Job.Status.PROVISIONING, Job.Status.TESTING):
            job.status = Job.Status.TESTING if job.wall_seconds < TEST_WINDOW_S else Job.Status.RUNNING
            job.status_message = "Bieg testowy" if job.status == Job.Status.TESTING else "Obliczenia w toku"
        if job.progress_t > 0 and job.wall_seconds > 30:
            job.eta_hours = (job.sim_time - job.progress_t) * (job.wall_seconds / job.progress_t) / 3600
    elif phase == "finishing":
        job.status, job.status_message = Job.Status.FINISHING, data.get("message", "Zapisuję wyniki")
    if "out_tail" in data:
        job.out_tail = str(data["out_tail"])[-20000:]
    if "log_tail" in data:
        job.log_tail = str(data["log_tail"])[-20000:]
    job.save()
    return JsonResponse({"action": "stop" if job.stop_requested else "continue"})


@require_POST
@agent_auth
def job_upload(request, job, name):
    if not SAFE_NAME.match(name) or name in (".", ".."):
        return HttpResponse("bad name", status=400)
    job.results_dir.mkdir(parents=True, exist_ok=True)
    target: Path = job.results_dir / name
    tmp = target.with_suffix(target.suffix + ".part")
    with open(tmp, "wb") as f:
        for chunk in iter(lambda: request.read(1024 * 1024), b""):
            f.write(chunk)
    tmp.replace(target)
    Job.objects.filter(id=job.id).update(last_heartbeat=timezone.now())
    return JsonResponse({"ok": True, "size": target.stat().st_size})


@require_POST
@agent_auth
def job_finish(request, job):
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponse("bad json", status=400)
    ok = data.get("status") == "done"
    msg = str(data.get("message", ""))[:1000]
    if job.stop_requested and not ok:
        status, msg = Job.Status.CANCELLED, msg or "Przerwane przez użytkownika"
    elif ok:
        status = Job.Status.DONE
    else:
        status = Job.Status.FAILED
        if job.wall_seconds and job.wall_seconds < TEST_WINDOW_S:
            msg = "Bieg testowy nie powiódł się: " + (msg or "FDS zakończył się błędem")
    if "wall_s" in data:
        job.wall_seconds = float(data["wall_s"])
        job.save(update_fields=["wall_seconds"])
    log_event(job, "agent_finish", f"{data.get('status')}: {msg}", actor="agent")
    tasks.finish_job.delay(job.id, status, msg)
    return JsonResponse({"ok": True})
