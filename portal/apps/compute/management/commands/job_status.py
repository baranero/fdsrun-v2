import json

from django.core.management.base import BaseCommand

from apps.jobs.models import Job


class Command(BaseCommand):
    help = "Print a job's state as JSON (used by the smoke-test workflow)."

    def add_arguments(self, parser):
        parser.add_argument("public_id")

    def handle(self, *args, **opts):
        j = Job.objects.get(public_id=opts["public_id"])
        machine = getattr(j, "machine", None)
        self.stdout.write(json.dumps({
            "id": j.public_id, "status": j.status, "message": j.status_message,
            "step": j.progress_step, "t": j.progress_t, "wall_s": j.wall_seconds, "cost_eur": j.cost_eur,
            "machine": machine.status if machine else None, "ip": machine.ip if machine else None,
            "n_files": len(j.result_files()),
            "files": [f["name"] for f in j.result_files() if not f["name"].endswith((".sf", ".sf.bnd", ".s3d", ".s3d.sz", ".s3dd", ".bf", ".bf.bnd", ".prt5", ".iso"))][:40],
            "out_tail": j.out_tail[-1500:], "log_tail": j.log_tail[-1500:],
            "events": [f"{e.at:%H:%M:%S} {e.kind} {e.detail[:120]}" for e in j.events.all()],
        }, ensure_ascii=False, indent=1))
