import secrets
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


def new_token():
    return secrets.token_urlsafe(32)


class Project(models.Model):
    """A folder of jobs: one building, one client, one thesis chapter."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=120)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("owner", "name")]

    def __str__(self):
        return self.name


class Job(models.Model):
    """One FDS calculation: an uploaded .fds file and everything that happens to it."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Analiza"            # uploaded and analyzed, not started
        QUEUED = "queued", "W kolejce"        # user pressed start
        PROVISIONING = "provisioning", "Tworzenie maszyny"
        TESTING = "testing", "Bieg testowy"   # first 2 minutes of the real run
        RUNNING = "running", "Liczy się"
        FINISHING = "finishing", "Zapis wyników"
        DONE = "done", "Zakończone"
        FAILED = "failed", "Błąd"
        CANCELLED = "cancelled", "Przerwane"
        STALLED = "stalled", "Brak odpowiedzi"

    ACTIVE = {Status.QUEUED, Status.PROVISIONING, Status.TESTING, Status.RUNNING, Status.FINISHING}

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="jobs")
    public_id = models.CharField(max_length=12, unique=True, editable=False)
    name = models.CharField(max_length=120)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs")
    note = models.TextField(blank=True)
    filename = models.CharField(max_length=255)
    chid = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.DRAFT, db_index=True)
    status_message = models.TextField(blank=True)

    # analysis (from analyzer/cli.js)
    analysis = models.JSONField(default=dict, blank=True)
    total_cells = models.BigIntegerField(default=0)
    n_meshes = models.PositiveIntegerField(default=0)
    sim_time = models.FloatField(default=0)

    # what the user chose
    procs = models.PositiveIntegerField(default=1)
    server_type = models.CharField(max_length=12, default="cpx42")
    fds_version = models.CharField(max_length=12, default="6.10.1")

    # estimate and billing basis (money itself comes in stage 3)
    est_hours = models.FloatField(default=0)
    est_cost_eur = models.FloatField(default=0)
    est_price_pln = models.FloatField(default=0)
    cost_eur = models.FloatField(default=0)      # actual, from machine run time
    price_pln = models.FloatField(default=0)     # actual, after multiplier

    # progress reported by the compute agent
    progress_step = models.BigIntegerField(default=0)
    progress_t = models.FloatField(default=0)
    progress_dt = models.FloatField(default=0)
    wall_seconds = models.FloatField(default=0)
    eta_hours = models.FloatField(null=True, blank=True)
    out_tail = models.TextField(blank=True)
    log_tail = models.TextField(blank=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)

    agent_token = models.CharField(max_length=64, default=new_token, editable=False)
    stop_requested = models.BooleanField(default=False)
    sync_requested_at = models.DateTimeField(null=True, blank=True)   # user asked for current files
    hidden_at = models.DateTimeField(null=True, blank=True)           # deleted by the client: files gone, row kept for billing
    files_synced_at = models.DateTimeField(null=True, blank=True)     # last file received from the machine
    # cost cap: when the projected time exceeds the estimate by 30%, the run pauses until the user confirms
    budget_confirmed = models.BooleanField(default=False)
    paused_at = models.DateTimeField(null=True, blank=True)
    projected_hours = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.public_id} {self.name}"

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = secrets.token_hex(4).upper()
        super().save(*args, **kwargs)

    # ----- files -----
    @property
    def dir(self) -> Path:
        return Path(settings.JOB_DATA_ROOT) / self.public_id

    @property
    def input_path(self) -> Path:
        return self.dir / "input" / self.filename

    @property
    def run_path(self) -> Path:
        """The file actually sent to the machine: input with MPI_PROCESS assigned for job.procs."""
        return self.dir / "run" / self.filename

    @property
    def results_dir(self) -> Path:
        return self.dir / "results"

    def result_files(self):
        if not self.results_dir.exists():
            return []
        files = []
        for p in sorted(self.results_dir.iterdir()):
            if p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size, "mtime": timezone.datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.get_current_timezone())})
        return files

    # ----- state helpers -----
    @property
    def is_active(self):
        return self.status in self.ACTIVE

    @property
    def is_paused(self):
        return self.paused_at is not None

    @property
    def projected_price_pln(self):
        if not self.projected_hours or not self.est_hours:
            return self.est_price_pln
        return self.est_price_pln * self.projected_hours / self.est_hours

    @property
    def eta_clock(self):
        """Expected finish as a datetime, or None."""
        if self.eta_hours is None or not self.is_active:
            return None
        return timezone.now() + timezone.timedelta(hours=self.eta_hours)

    @property
    def cfl_max(self):
        """Last 'Max CFL number' reported in the .out tail, or None."""
        import re

        m = re.findall(r"Max CFL number:\s*([0-9.E+-]+)", self.out_tail or "")
        try:
            return float(m[-1]) if m else None
        except ValueError:
            return None

    @property
    def wall_text(self):
        """Wall time as '1 h 58 min' / '12 min' / '45 s'."""
        s = int(self.wall_seconds or 0)
        if s < 60:
            return f"{s} s"
        h, m = divmod(s // 60, 60)
        return f"{h} h {m:02d} min" if h else f"{m} min"

    @property
    def progress_pct(self):
        if not self.sim_time:
            return 0
        return min(100, round(100 * self.progress_t / self.sim_time))

    def set_status(self, status, message=""):
        self.status = status
        if message:
            self.status_message = message
        if status in (self.Status.DONE, self.Status.FAILED, self.Status.CANCELLED, self.Status.STALLED) and not self.finished_at:
            self.finished_at = timezone.now()
            self.expires_at = self.finished_at + timezone.timedelta(days=settings.PRICING["results_days"])
        self.save()


class JobEvent(models.Model):
    """Audit trail: who did what to a job, including admin access to files."""

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField(auto_now_add=True)
    actor = models.CharField(max_length=120, blank=True)  # user e-mail, "agent", "system"
    kind = models.CharField(max_length=40)
    detail = models.TextField(blank=True)

    class Meta:
        ordering = ["at"]


def log_event(job, kind, detail="", actor="system"):
    JobEvent.objects.create(job=job, kind=kind, detail=detail[:4000], actor=actor)
