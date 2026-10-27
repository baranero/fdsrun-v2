from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send a test e-mail to ADMIN_EMAIL (or the given address) to verify SMTP settings."

    def add_arguments(self, parser):
        parser.add_argument("to", nargs="?", default="")

    def handle(self, *args, **opts):
        to = opts["to"] or settings.ADMIN_EMAIL
        self.stdout.write(f"backend={settings.EMAIL_BACKEND} host={settings.EMAIL_HOST!r} port={settings.EMAIL_PORT} user={settings.EMAIL_HOST_USER!r} from={settings.DEFAULT_FROM_EMAIL!r} to={to!r}")
        n = send_mail(
            "fdsrun: test poczty",
            "To jest wiadomość testowa z portalu fdsrun. Jeśli ją czytasz, wysyłka e-maili działa.",
            settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False,
        )
        self.stdout.write(f"sent={n}")
