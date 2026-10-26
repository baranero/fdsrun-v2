import json

from django.core.management.base import BaseCommand

from apps.jobs.models import Job


class Command(BaseCommand):
    help = "Recent jobs with status and last events (diagnostics)."

    def handle(self, *args, **opts):
        rows = []
        for j in Job.objects.select_related("owner").order_by("-created_at")[:20]:
            rows.append({"id": j.public_id, "owner": j.owner.email, "name": j.name, "status": j.status, "message": j.status_message[:200],
                         "created": j.created_at.strftime("%d.%m %H:%M"), "events": [f"{e.kind}: {e.detail[:150]}" for e in j.events.order_by("-at")[:4]]})
        self.stdout.write(json.dumps(rows, ensure_ascii=False, indent=1))
