from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.compute import tasks as compute_tasks

from . import archives, charts
from .analyzer import AnalyzerError, analyze_file, multiplier_for, prepare_run_file
from .forms import JobEditForm, StartForm, UploadForm
from .models import Job, Project, log_event


def _own_job(request, public_id):
    job = get_object_or_404(Job, public_id=public_id)
    if job.owner_id != request.user.id and not request.user.is_staff:
        raise Http404
    if job.hidden_at and not request.user.is_staff:
        raise Http404
    if request.user.is_staff and job.owner_id != request.user.id:
        log_event(job, "admin_view", request.path, actor=request.user.email)
    return job


@login_required
def dashboard(request):
    mine = Job.objects.filter(owner=request.user, hidden_at__isnull=True)
    active = [j for j in mine.filter(status__in=Job.ACTIVE)]
    recent = mine.exclude(status__in=Job.ACTIVE).exclude(status=Job.Status.DRAFT)[:8]
    drafts = mine.filter(status=Job.Status.DRAFT)[:5]
    now = timezone.now()
    month = mine.filter(finished_at__year=now.year, finished_at__month=now.month)
    spent = sum(j.price_pln for j in month)
    hours = sum((j.wall_seconds or 0) for j in month) / 3600
    projected = spent + sum(j.projected_price_pln for j in active)
    storage = 0
    for j in mine.exclude(status=Job.Status.DRAFT):
        if j.results_dir.exists():
            storage += sum(p.stat().st_size for p in j.results_dir.iterdir() if p.is_file())
            if archives.archive_dir(j).exists():
                storage += sum(p.stat().st_size for p in archives.archive_dir(j).iterdir() if p.is_file())
    recent = [dict(job=j, archive=next((a for a in archives.ready_archives(j) if a["key"] == "csv"), None)) for j in recent]
    return render(request, "jobs/dashboard.html", {
        "active": active, "recent": recent, "drafts": drafts,
        "n_running": sum(1 for j in active if j.status == Job.Status.RUNNING),
        "n_preparing": sum(1 for j in active if j.status != Job.Status.RUNNING),
        "spent": spent, "projected": projected, "month_jobs": month.count(), "month_hours": hours,
        "month_done": month.filter(status=Job.Status.DONE).count(), "month_bad": month.exclude(status=Job.Status.DONE).count(),
        "total_jobs": mine.exclude(status=Job.Status.DRAFT).count(), "storage": storage,
    })


LIST_FILTERS = {
    "": ("Wszystkie", None),
    "active": ("W toku", lambda q: q.filter(status__in=Job.ACTIVE)),
    "done": ("Zakończone", lambda q: q.filter(status=Job.Status.DONE)),
    "problem": ("Błędy i przerwane", lambda q: q.filter(status__in=[Job.Status.FAILED, Job.Status.STALLED, Job.Status.CANCELLED])),
    "draft": ("Nieuruchomione", lambda q: q.filter(status=Job.Status.DRAFT)),
}


@login_required
def job_list(request):
    jobs = Job.objects.filter(owner=request.user, hidden_at__isnull=True)
    flt = request.GET.get("f", "")
    if flt not in LIST_FILTERS:
        flt = ""
    if LIST_FILTERS[flt][1]:
        jobs = LIST_FILTERS[flt][1](jobs)
    q = request.GET.get("q", "").strip()
    if q:
        from django.db.models import Q

        jobs = jobs.filter(Q(name__icontains=q) | Q(public_id__icontains=q) | Q(chid__icontains=q) | Q(filename__icontains=q))
    from django.core.paginator import Paginator
    from django.db.models import Count, Q, Sum

    mine = Job.objects.filter(owner=request.user, hidden_at__isnull=True)
    projects = Project.objects.filter(owner=request.user).annotate(n=Count("jobs", filter=Q(jobs__hidden_at__isnull=True)))
    proj = request.GET.get("p", "")
    if proj == "none":
        jobs = jobs.filter(project__isnull=True)
    elif proj:
        jobs = jobs.filter(project__name=proj)
    counts = {k: (v[1](mine) if v[1] else mine).count() for k, v in LIST_FILTERS.items()}
    total_price = jobs.aggregate(s=Sum("price_pln"))["s"] or 0
    page = Paginator(jobs.select_related("project"), 25).get_page(request.GET.get("page"))
    # Grupy na liście (jak na pulpicie): w toku, nieuruchomione, zakończone, błędy i przerwane.
    groups_def = [
        ("running", "W toku", lambda j: j.is_active),
        ("draft", "Nieuruchomione", lambda j: j.status == Job.Status.DRAFT),
        ("done", "Zakończone", lambda j: j.status == Job.Status.DONE),
        ("failed", "Błędy i przerwane", lambda j: True),
    ]
    groups, rest = [], list(page.object_list)
    for icon, label, pred in groups_def:
        rows = [j for j in rest if pred(j)]
        rest = [j for j in rest if j not in rows]
        if rows:
            groups.append({"icon": icon, "label": label, "rows": rows})
    return render(request, "jobs/list.html", {
        "jobs": page.object_list, "groups": groups, "page": page, "flt": flt, "q": q, "proj": proj, "projects": projects,
        "filters": [(k, v[0], counts[k]) for k, v in LIST_FILTERS.items()],
        "no_project": mine.filter(project__isnull=True).count(),
        "shown": len(page.object_list), "matched": page.paginator.count, "total_price": total_price,
        "poll": jobs.filter(status__in=Job.ACTIVE).exists(),
    })


def _project_for(user, name):
    name = (name or "").strip()
    if not name:
        return None
    project, _ = Project.objects.get_or_create(owner=user, name=name[:120])
    return project


@login_required
@require_POST
def job_sync(request, public_id):
    """Ask the machine to send everything it has now (instead of waiting up to 5 minutes)."""
    job = _own_job(request, public_id)
    if job.is_active:
        job.sync_requested_at = timezone.now()
        job.save(update_fields=["sync_requested_at"])
        log_event(job, "sync_requested", actor=request.user.email)
        messages.info(request, "Maszyna dośle bieżące pliki w ciągu kilkunastu sekund (duże pliki — tylko przyrost od ostatniej wysyłki).")
    return redirect(reverse("jobs:detail", args=[public_id]) + "#pliki")


@login_required
@require_POST
def job_snapshot(request, public_id):
    """Pack one archive kind (?key=csv|smokeview|all) from what the portal holds now — during
    the run (current state) or after it (large archives are made on request only)."""
    job = _own_job(request, public_id)
    key = request.POST.get("key", "csv")
    if key not in {k for k, *_ in archives.ARCHIVES}:
        raise Http404
    item = next((a for a in archives.archive_files(job) if a["key"] == key), None)
    if not item or item["building"]:
        return redirect(reverse("jobs:detail", args=[public_id]) + "#pliki")
    if not archives.room_for(item["est_size"]):
        messages.error(request, "Na serwerze brakuje teraz miejsca na to archiwum. Pobierz pliki pojedynczo albo archiwum „CSV i logi” — napisaliśmy już do administratora.")
        from . import notify

        notify.admin_alert("brak miejsca na archiwum", f"{job.public_id} {job.name}: archiwum {key} ({item['est_size'] // 2**20} MB) nie mieści się na dysku.")
        return redirect(reverse("jobs:detail", args=[public_id]) + "#pliki")
    d = archives.archive_dir(job)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"building-{key}").write_text("1\n")
    try:
        archives.build_archives_task.delay(job.id, [key])
    except Exception:  # noqa: BLE001  (queue down: do not leave a stuck "packing" marker)
        (d / f"building-{key}").unlink(missing_ok=True)
        messages.error(request, "Nie udało się zlecić pakowania — spróbuj za chwilę. Pojedyncze pliki możesz pobierać od razu.")
        return redirect(reverse("jobs:detail", args=[public_id]) + "#pliki")
    log_event(job, "archive_requested", key, actor=request.user.email)
    messages.info(request, "Pakuję archiwum. Pojawi się tu za chwilę (duże — kilka minut).")
    return redirect(reverse("jobs:detail", args=[public_id]) + "#pliki")


@login_required
@require_POST
def job_resume(request, public_id):
    from apps.billing.services import can_start

    from .resume import resume, resumable

    job = _own_job(request, public_id)
    if not resumable(job):
        messages.error(request, "Tego zlecenia nie da się wznowić.")
        return redirect("jobs:detail", public_id=public_id)
    left = max(0.05, 1 - (job.progress_t or 0) / job.sim_time) if job.sim_time else 1
    ok, why = can_start(request.user, job.est_price_pln * left)
    if not ok:
        if why == "profile":
            return redirect(reverse("billing:profile") + "?next=" + reverse("jobs:detail", args=[public_id]))
        messages.error(request, why)
        return redirect("jobs:detail", public_id=public_id)
    new = resume(job, request.user.email)
    compute_tasks.launch_job.delay(new.id)
    messages.success(request, f"Wznawiam obliczenia od ostatniego zapisu. Wyniki poprzedniego biegu są w tym zleceniu i FDS będzie je uzupełniał.")
    return redirect("jobs:detail", public_id=new.public_id)


@login_required
@require_POST
def job_delete(request, public_id):
    """Delete a finished job with all its files. Irreversible; the page asks first."""
    from django.template.defaultfilters import filesizeformat

    from .purge import hide_job

    job = _own_job(request, public_id)
    if job.is_active:
        messages.error(request, "Tego zlecenia nie można usunąć, dopóki się liczy — najpierw je zatrzymaj.")
        return redirect("jobs:detail", public_id=public_id)
    name = job.name
    freed = hide_job(job)
    log_event(job, "hidden", f"{freed} B", actor=request.user.email)
    messages.success(request, f"Usunięto zlecenie „{name}” i jego pliki ({filesizeformat(freed)}).")
    return redirect("jobs:list")


@login_required
@require_POST
def job_edit(request, public_id):
    job = _own_job(request, public_id)
    form = JobEditForm(request.POST)
    if form.is_valid():
        job.name = form.cleaned_data["name"]
        job.note = form.cleaned_data["note"]
        job.project = _project_for(job.owner, form.cleaned_data["project"])
        job.save(update_fields=["name", "note", "project"])
        messages.success(request, "Zapisano.")
    else:
        messages.error(request, "Nie udało się zapisać zmian.")
    return redirect("jobs:detail", public_id=public_id)


@login_required
def job_new(request):
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["file"]
        job = Job(owner=request.user, name=f.name.rsplit(".", 1)[0][:120], filename=f.name, project=_project_for(request.user, form.cleaned_data.get("project")))
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
            return render(request, "jobs/new.html", {"form": form, "max_mb": settings.MAX_UPLOAD_MB, "projects": Project.objects.filter(owner=request.user), "preset": request.GET.get("p", "")})
        _apply_analysis(job, data)
        log_event(job, "uploaded", f"{f.name}, {f.size} B", actor=request.user.email)
        return redirect("jobs:detail", public_id=job.public_id)
    return render(request, "jobs/new.html", {"form": form, "max_mb": settings.MAX_UPLOAD_MB, "projects": Project.objects.filter(owner=request.user), "preset": request.GET.get("p", "")})


def _issues_with_source(job):
    """Validation issues plus the quoted source line for those that point at a line."""
    issues = [dict(i) for i in job.analysis.get("issues", [])]
    wanted = {i["line"] for i in issues if i.get("line")}
    if wanted and job.input_path.is_file():
        try:
            with open(job.input_path, errors="replace") as fh:
                lines = {n: line.rstrip("\n")[:200] for n, line in enumerate(fh, 1) if n in wanted}
        except OSError:
            lines = {}
        for i in issues:
            if i.get("line") in lines:
                i["src"] = lines[i["line"]]
    order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: order.get(i["level"], 3))
    return issues


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
    issues = _issues_with_source(job)
    errors = [i for i in issues if i["level"] == "error"]
    ctx = {
        "job": job,
        "issues": issues,
        "issue_counts": {lvl: sum(1 for i in issues if i["level"] == lvl) for lvl in ("error", "warn", "info")},
        "has_errors": bool(errors),
        "options": job.analysis.get("advice", {}).get("best", []),
        "tips": job.analysis.get("advice", {}).get("tips", []),
        "cheapest": job.analysis.get("advice", {}).get("cheapest") or {},
        "fastest": job.analysis.get("advice", {}).get("fastest") or {},
        "confidence": job.analysis.get("estimate", {}).get("confidence", {}),
        "files": job.result_files(),
        "events": job.events.order_by("at"),
        "edit_form": JobEditForm(initial={"name": job.name, "project": job.project.name if job.project else "", "note": job.note}),
        "projects": Project.objects.filter(owner=job.owner),
        "meshes": job.analysis.get("model", {}).get("meshes", []),
        "model": job.analysis.get("model", {}),
    }
    ctx["file_groups"] = archives.group_files(ctx["files"])
    ctx["archives"] = archives.archive_files(job)
    ctx["archives_ready"] = [a for a in ctx["archives"] if a["ready"]]
    ctx["archives_building"] = any(a["building"] for a in ctx["archives"])
    ctx["archives_pending"] = ctx["archives_building"]
    ctx["archive_hours"] = archives.LARGE_ARCHIVE_HOURS
    from .resume import resumable

    ctx["resumable"] = resumable(job)
    ctx["resumed_as"] = job.restarts.first()
    ctx["files_size"] = sum(f["size"] for f in ctx["files"])
    if request.htmx:
        return render(request, "jobs/_status.html", ctx)
    return render(request, "jobs/detail.html", ctx)




CONSOLE_LINES = 600


@login_required
def job_console(request, public_id):
    """Tail of the FDS .out file (the terminal view), refreshed by HTMX while the job runs."""
    job = _own_job(request, public_id)
    text = ""
    path = job.results_dir / f"{job.chid}.out" if job.chid else None
    if path and path.is_file():
        try:
            with open(path, "rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 120_000))
                text = fh.read().decode("utf-8", "replace")
        except OSError:
            text = ""
        lines = text.splitlines()[-CONSOLE_LINES:]
        if size > 120_000:
            lines = lines[1:]
        text = "\n".join(lines)
    elif job.out_tail:
        text = job.out_tail
    if job.status == Job.Status.FAILED and job.log_tail:
        text = (text + "\n\n--- wyjście programu ---\n" + job.log_tail).strip()
    return render(request, "jobs/_console.html", {"job": job, "text": text, "n_lines": text.count("\n") + 1 if text else 0})


@login_required
def job_charts(request, public_id):
    """JSON for the live charts: HRR and device readings grouped by unit."""
    job = _own_job(request, public_id)
    from django.http import JsonResponse

    return JsonResponse({
        "t_end": job.sim_time,
        "hrr": charts.hrr_series(job.results_dir, job.chid),
        "devc": charts.devc_series(job.results_dir, job.chid),
    })


@login_required
@require_POST
def job_start(request, public_id):
    job = _own_job(request, public_id)
    if job.status != Job.Status.DRAFT:
        return HttpResponseForbidden("Zlecenie już uruchomione")
    # the confirmation link can only arrive once outgoing mail is configured
    if settings.EMAIL_HOST and not request.user.email_confirmed and not request.user.is_staff:
        messages.error(request, "Najpierw potwierdź adres e-mail — link jest w wiadomości, którą wysłaliśmy po rejestracji.")
        return redirect("jobs:detail", public_id=public_id)
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
    from apps.billing.services import can_start

    ok, why = can_start(request.user, opt["pricePln"])
    if not ok:
        if why == "profile":
            messages.info(request, "Zanim uruchomisz pierwsze obliczenia, podaj dane do faktury. Płatność i tak dopiero po wynikach.")
            return redirect(reverse("billing:profile") + "?next=" + reverse("jobs:detail", args=[public_id]))
        messages.error(request, why)
        return redirect("jobs:detail", public_id=public_id)
    job.procs, job.server_type = opt["procs"], opt["server"]
    job.est_hours, job.est_cost_eur, job.est_price_pln = opt["hours"], opt["costEur"], opt["pricePln"]
    try:
        info = prepare_run_file(job.input_path, job.run_path, job.procs)
    except AnalyzerError as e:
        messages.error(request, str(e))
        return redirect("jobs:detail", public_id=public_id)
    log_event(job, "run_file", f"MPI_PROCESS assigned for {info['procs']} processes, busiest {info['maxLoad']} cells", actor="system")
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
    """Old per-file URL: hand over to /pobierz/, which Caddy serves with Range support."""
    job = _own_job(request, public_id)
    if not archives.resolve(job, name):
        raise Http404
    return redirect(archives.download_url(job, name))
