from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.jobs import archives
from apps.jobs.models import Job


class Command(BaseCommand):
    help = "Print a signed 7-day download link for a job's archive (default: the 'all' archive)."

    def add_arguments(self, parser):
        parser.add_argument("public_id")
        parser.add_argument("--key", default="all")

    def handle(self, *args, **opts):
        job = Job.objects.get(public_id=opts["public_id"])
        items = {a["key"]: a for a in archives.archive_files(job)}
        if opts["key"] not in items:
            raise CommandError(f"no archive '{opts['key']}' (have: {', '.join(items) or 'none'})")
        self.stdout.write(settings.PORTAL_URL.rstrip("/") + archives.download_url(job, items[opts["key"]]["name"], signed=True))
