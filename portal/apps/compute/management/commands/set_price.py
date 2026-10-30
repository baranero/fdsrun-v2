from django.core.management.base import BaseCommand

from apps.jobs.models import Job, log_event


class Command(BaseCommand):
    help = "Set a job's final price (e.g. 0 for a run lost through our fault)."

    def add_arguments(self, parser):
        parser.add_argument("public_id")
        parser.add_argument("price")

    def handle(self, *args, **opts):
        job = Job.objects.get(public_id=opts["public_id"])
        old = job.price_pln
        job.price_pln = float(opts["price"])
        job.save(update_fields=["price_pln"])
        log_event(job, "price_set", f"{old} -> {job.price_pln} zł", actor="admin-cli")
        self.stdout.write(f"{job.public_id}: {old} -> {job.price_pln}")
