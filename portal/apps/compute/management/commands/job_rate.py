import re
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.jobs.models import Job

STEP = re.compile(r"^\s*Time Step\s+(\d+)\s+(\w+ \d+, \d{4}\s+\d\d:\d\d:\d\d)")
SIZE = re.compile(r"^\s*Step Size:\s*([0-9.E+-]+) s, Total Time:\s*([0-9.E+-]+) s")


class Command(BaseCommand):
    help = "Progress history of a job from its .out: wall seconds, step, sim time, dt — for checking the ETA model."

    def add_arguments(self, parser):
        parser.add_argument("public_id")
        parser.add_argument("--points", type=int, default=40)

    def handle(self, *args, **opts):
        job = Job.objects.get(public_id=opts["public_id"])
        path = job.results_dir / f"{job.chid}.out"
        if not path.is_file():
            raise CommandError("no .out file")
        rows, step, when = [], None, None
        for line in open(path, errors="replace"):
            m = STEP.match(line)
            if m:
                step, when = int(m.group(1)), datetime.strptime(m.group(2), "%B %d, %Y %H:%M:%S")
                continue
            m = SIZE.match(line)
            if m and step is not None:
                rows.append((when, step, float(m.group(2)), float(m.group(1))))
                step = None
        if not rows:
            raise CommandError("no steps found")
        t0 = rows[0][0]
        n = opts["points"]
        pick = rows if len(rows) <= n else [rows[int(i * (len(rows) - 1) / (n - 1))] for i in range(n)]
        self.stdout.write(f"sim_time={job.sim_time} est_hours={job.est_hours:.2f} wall_total={(rows[-1][0] - t0).total_seconds():.0f}s steps={rows[-1][1]}")
        self.stdout.write("wall_s,step,t,dt")
        for when, s, t, dt in pick:
            self.stdout.write(f"{(when - t0).total_seconds():.0f},{s},{t:.2f},{dt:.5f}")
