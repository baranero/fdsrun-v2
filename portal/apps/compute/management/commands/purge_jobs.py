import shutil

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.defaultfilters import filesizeformat

from apps.jobs.models import Job
from apps.jobs.purge import dir_size, purge_job


class Command(BaseCommand):
    help = "Delete finished jobs (files and database rows). Without --yes only lists what would go."

    def add_arguments(self, parser):
        parser.add_argument("public_ids", nargs="*")
        parser.add_argument("--all-finished", action="store_true", help="every job that is not running")
        parser.add_argument("--except", dest="keep", default="", help="comma-separated public ids to keep")
        parser.add_argument("--yes", action="store_true", help="really delete")

    def handle(self, *args, **opts):
        if opts["all_finished"]:
            jobs = Job.objects.exclude(status__in=Job.ACTIVE)
        elif opts["public_ids"]:
            jobs = Job.objects.filter(public_id__in=opts["public_ids"])
        else:
            raise CommandError("give public ids or --all-finished")
        keep = {k.strip().upper() for k in opts["keep"].split(",") if k.strip()}
        jobs = [j for j in jobs.select_related("owner") if j.public_id not in keep]
        total = 0
        for j in jobs:
            size = dir_size(j.dir)
            total += size
            flag = "ACTIVE, skipped" if j.is_active else ""
            self.stdout.write(f"{j.public_id} {j.owner.email:<24} {j.status:<10} {filesizeformat(size):>10}  {j.name} {flag}")
        self.stdout.write(f"{len(jobs)} jobs, {filesizeformat(total)}" + ("" if opts["yes"] else " — dry run, add --yes to delete"))
        if opts["yes"]:
            freed = 0
            for j in jobs:
                if not j.is_active:
                    freed += purge_job(j)
            self.stdout.write(f"deleted, freed {filesizeformat(freed)}")
        du = shutil.disk_usage(settings.JOB_DATA_ROOT)
        self.stdout.write(f"disk: {filesizeformat(du.used)} used, {filesizeformat(du.free)} free of {filesizeformat(du.total)}")
