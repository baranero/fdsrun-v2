from django.core.management.base import BaseCommand, CommandError

from apps.jobs.models import Job


class Command(BaseCommand):
    help = "Print the head of a result file plus lines matching an expression (diagnostics)."

    def add_arguments(self, parser):
        parser.add_argument("public_id")
        parser.add_argument("name")
        parser.add_argument("--head", type=int, default=60)
        parser.add_argument("--grep", default="ERROR|Killed|memory|Memory|signal")

    def handle(self, *args, **opts):
        import re

        job = Job.objects.get(public_id=opts["public_id"])
        path = job.results_dir / opts["name"]
        if not path.is_file():
            raise CommandError("no such file")
        lines = path.read_text(errors="replace").splitlines()
        self.stdout.write(f"{opts['name']}: {len(lines)} lines\n--- head")
        self.stdout.write("\n".join(lines[: opts["head"]]))
        rx = re.compile(opts["grep"])
        self.stdout.write("--- matches")
        self.stdout.write("\n".join(f"{i + 1}: {l}" for i, l in enumerate(lines) if rx.search(l))[:6000])
