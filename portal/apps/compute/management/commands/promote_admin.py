from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Give an existing account staff + superuser rights (admin panel access)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    def handle(self, *args, **opts):
        try:
            u = User.objects.get(email=opts["email"])
        except User.DoesNotExist:
            raise CommandError(f"no account with e-mail {opts['email']}; register it in the portal first")
        u.is_staff = u.is_superuser = True
        u.save(update_fields=["is_staff", "is_superuser"])
        self.stdout.write(f"{u.email} is now an admin")
