"""Owner's panel: everything in one place. Only staff may enter; every visit to a
client's job or file is written to the job's event log (visible to the client too)."""

from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.compute.models import Machine, ServerCalibration
from apps.jobs.models import Job, JobEvent, log_event

FINAL = [Job.Status.DONE, Job.Status.FAILED, Job.Status.CANCELLED, Job.Status.STALLED]


def _money(qs):
    agg = qs.aggregate(revenue=Sum("price_pln"), cost=Sum("cost_eur"), n=Count("id"), hours=Sum("wall_seconds"))
    revenue = agg["revenue"] or 0
    cost_eur = agg["cost"] or 0
    from django.conf import settings

    cost_pln = cost_eur * settings.PRICING["eur_pln"]
    return {"revenue": revenue, "cost_eur": cost_eur, "cost_pln": cost_pln, "margin": revenue - cost_pln, "n": agg["n"], "hours": (agg["hours"] or 0) / 3600}


@staff_member_required
def dashboard(request):
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    finished = Job.objects.filter(status__in=FINAL).exclude(owner__email__endswith="fdsrun.internal")
    ctx = {
        "active": Job.objects.filter(status__in=Job.ACTIVE).select_related("owner"),
        "machines": Machine.objects.exclude(status=Machine.Status.DELETED).select_related("job"),
        "month": _money(finished.filter(finished_at__gte=month_start)),
        "total": _money(finished),
        "by_month": [
            {**_money(finished.filter(finished_at__gte=m, finished_at__lt=m + timedelta(days=32)).filter(finished_at__month=m.month)), "month": m}
            for m in finished.annotate(m=TruncMonth("finished_at")).values_list("m", flat=True).distinct().order_by("-m")[:12]
        ],
        "users": User.objects.count(),
        "users_month": User.objects.filter(date_joined__gte=month_start).count(),
        "recent": Job.objects.select_related("owner").order_by("-created_at")[:15],
        "calibration": ServerCalibration.objects.all(),
        "accuracy": finished.filter(status=Job.Status.DONE, est_hours__gt=0, wall_seconds__gt=0).order_by("-finished_at")[:20],
        "lost": Machine.objects.filter(status=Machine.Status.LOST),
    }
    return render(request, "panel/dashboard.html", ctx)


@staff_member_required
def jobs(request):
    qs = Job.objects.select_related("owner").order_by("-created_at")
    status = request.GET.get("status")
    q = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(public_id__icontains=q) | Q(name__icontains=q) | Q(owner__email__icontains=q) | Q(chid__icontains=q))
    return render(request, "panel/jobs.html", {"jobs": qs[:200], "status": status or "", "q": q, "statuses": Job.Status.choices})


@staff_member_required
def users(request):
    qs = User.objects.annotate(n_jobs=Count("jobs", distinct=True), revenue=Sum("jobs__price_pln"), last_job=Max("jobs__created_at")).order_by("-date_joined")
    return render(request, "panel/users.html", {"users": qs, "kinds": User.Kind.choices})


@staff_member_required
@require_POST
def user_update(request, user_id):
    u = get_object_or_404(User, id=user_id)
    u.kind = request.POST.get("kind", u.kind)
    u.trusted = request.POST.get("trusted") == "on"
    u.student_verified = request.POST.get("student_verified") == "on"
    u.is_active = request.POST.get("is_active") == "on"
    try:
        u.per_job_limit_pln = float(request.POST.get("per_job_limit_pln", u.per_job_limit_pln))
    except ValueError:
        pass
    u.save()
    messages.success(request, f"Zapisano {u.email}")
    return redirect("panel:users")


@staff_member_required
def access_log(request):
    events = JobEvent.objects.filter(kind__in=["admin_view", "download"]).exclude(actor="").select_related("job", "job__owner").order_by("-at")[:300]
    admin_events = [e for e in events if e.actor and User.objects.filter(email=e.actor, is_staff=True).exists() and e.job.owner.email != e.actor]
    return render(request, "panel/access.html", {"events": admin_events})


@staff_member_required
def machines(request):
    qs = Machine.objects.select_related("job", "job__owner").order_by("-created_at")[:200]
    return render(request, "panel/machines.html", {"machines": qs})


@staff_member_required
@require_POST
def machine_delete(request, machine_id):
    from apps.compute import tasks

    m = get_object_or_404(Machine, id=machine_id)
    if m.job is None:
        messages.info(request, f"Maszyna {m.name} jest już usunięta.")
        return redirect("panel:machines")
    if m.job.is_active:
        tasks.finish_job.delay(m.job_id, Job.Status.CANCELLED, "Przerwane przez administratora")
    else:
        tasks.delete_machine.delay(m.job_id)
    if m.job:
        log_event(m.job, "admin_machine_delete", m.name, actor=request.user.email)
    messages.info(request, f"Usuwam maszynę {m.name}")
    return redirect("panel:machines")
