import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.compute import tasks as compute_tasks

from .analyzer import AnalyzerError, analyze_file, multiplier_for
from .forms import StartForm, UploadForm
from .models import Job, log_event


def _own_job(request, public_id):
    job = get_object_or_404(Job, public_id=public_id)
    if job.owner_id != request.user.id and not request.user.is_staff:
        raise Http404
    if request.user.is_staff and job.owner_id != request.user.id:
        log_event(job, "admin_view", request.path, actor=request.user.email)
    return job


@login_required
def job_list(request):
    jobs = Job.objects.filter(owner=request.user)
    return render(request, "jobs/list.html", {"jobs": jobs})


@login_required
def job_new(request):
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["file"]
        job = Job(owner=request.user, name=f.name.rsplit(".", 1)[0][:120], filename=f.name)
        job.save()
        job.input_path.parent.mkdir(parents=True, exist_ok=True)
        with open(job.input_path, "wb") as dst:
            for chunk in f.chunks():
                dst.write(chunk)
        try:
            data = analyze_file(job.input_path, multiplier_for(request.user))
        except AnalyzerError as e:
            job.delete()
            messages.error(request, f"Nie udało się przeanalizować pliku: {e}")
            return render(request, "jobs/new.html", {"form": form})
        _apply_analysis(job, data)
        log_event(job, "uploaded", f"{f.name}, {f.size} B", actor=request.user.email)
        return redirect("jobs:detail", public_id=job.public_id)
    return render(request, "jobs/new.html", {"form": form})


def _apply_analysis(job, data):
    m = data["model"]
    job.analysis = data
    job.chid = m.get("chid", "")[:120]
    job.total_cells = m["totalCells"]
    job.n_meshes = len(m["meshes"])
    job.sim_time = m["simTime"]
    pick = data["advice"].get("cheapest") or data["advice"].get("current")
    if pick:
        job.procs = pick["procs"]
        job.server_type = pick["server"]
        job.est_hours = pick["hours"]
        job.est_cost_eur = pick["costEur"]
        job.est_price_pln = pick["pricePln"]
    job.save()


@login_required
def job_detail(request, public_id):
    job = _own_job(request, public_id)
    errors = [i for i in job.analysis.get("issues", []) if i["level"] == "error"]
    ctx = {
        "job": job,
        "issues": job.analysis.get("issues", []),
        "has_errors": bool(errors),
        "options": job.analysis.get("advice", {}).get("best", []),
        "tips": job.analysis.get("advice", {}).get("tips", []),
        "confidence": job.analysis.get("estimate", {}).get("confidence", {}),
        "files": job.result_files(),
    }
    if request.htmx:
        return render(request, "jobs/_status.html", ctx)
    return render(request, "jobs/detail.html", ctx)


@login_required
@require_POST
def job_start(request, public_id):
    job = _own_job(request, public_id)
    if job.status != Job.Status.DRAFT:
        return HttpResponseForbidden("Zlecenie już uruchomione")
    if any(i["level"] == "error" for i in job.analysis.get("issues", [])):
        messages.error(request, "Plik ma błędy, które zatrzymają FDS. Popraw je i wgraj ponownie.")
        return redirect("jobs:detail", public_id=public_id)
    form = StartForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Niepoprawny wybór serwera.")
        return redirect("jobs:detail", public_id=public_id)
    opt = next((o for o in job.analysis["advice"]["options"] if o["procs"] == form.cleaned_data["procs"] and o["server"] == form.cleaned_data["server_type"]), None)
    if opt is None:
        messages.error(request, "Wybierz jeden z wariantów z tabeli.")
        return redirect("jobs:detail", public_id=public_id)
    job.procs, job.server_type = opt["procs"], opt["server"]
    job.est_hours, job.est_cost_eur, job.est_price_pln = opt["hours"], opt["costEur"], opt["pricePln"]
    job.started_at = timezone.now()
    job.set_status(Job.Status.QUEUED, "Czeka na maszynę")
    log_event(job, "start", f"{job.procs} proc, {job.server_type}, est {job.est_hours:.1f} h", actor=request.user.email)
    compute_tasks.launch_job.delay(job.id)
    return redirect("jobs:detail", public_id=public_id)


@login_required
@require_POST
def job_stop(request, public_id):
    job = _own_job(request, public_id)
    if job.is_active:
        job.stop_requested = True
        job.save(update_fields=["stop_requested"])
        log_event(job, "stop_requested", actor=request.user.email)
        compute_tasks.stop_job.delay(job.id)
        messages.info(request, "Zatrzymuję obliczenia. Wyniki do tej chwili zostaną zapisane.")
    return redirect("jobs:detail", public_id=public_id)


@login_required
@require_POST
def job_continue(request, public_id):
    job = _own_job(request, public_id)
    if job.is_paused:
        job.budget_confirmed = True
        job.paused_at = None
        job.status_message = "Obliczenia wznowione"
        job.save(update_fields=["budget_confirmed", "paused_at", "status_message"])
        log_event(job, "budget_confirmed", f"{job.projected_hours or 0:.2f} h", actor=request.user.email)
    return redirect("jobs:detail", public_id=public_id)


@login_required
def job_file(request, public_id, name):
    job = _own_job(request, public_id)
    path = (job.results_dir / name).resolve()
    if not str(path).startswith(str(job.results_dir.resolve())) or not path.is_file():
        raise Http404
    log_event(job, "download", name, actor=request.user.email)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return FileResponse(open(path, "rb"), as_attachment=True, filename=name, content_type=ctype)
