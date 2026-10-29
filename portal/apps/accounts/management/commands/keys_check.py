from django.conf import settings
from django.core.management.base import BaseCommand


def _describe(value, test_prefix=None):
    if not value:
        return "brak"
    mode = ""
    if test_prefix is not None:
        mode = ", tryb TESTOWY" if value.startswith(test_prefix) else ", tryb PRODUKCYJNY (live)"
    return f"jest ({len(value)} znaków{mode})"


class Command(BaseCommand):
    help = "Report which payment/invoicing keys reached the server, without printing them."

    def handle(self, *args, **opts):
        self.stdout.write(f"STRIPE_SECRET_KEY: {_describe(settings.STRIPE_SECRET_KEY, 'sk_test_')}")
        self.stdout.write(f"STRIPE_PUBLISHABLE_KEY: {_describe(settings.STRIPE_PUBLISHABLE_KEY, 'pk_test_')}")
        self.stdout.write(f"STRIPE_WEBHOOK_SECRET: {_describe(settings.STRIPE_WEBHOOK_SECRET)}")
        self.stdout.write(f"ING_API_KEY: {_describe(settings.ING_API_KEY)}")
        if settings.STRIPE_SECRET_KEY:
            try:
                import requests

                r = requests.get("https://api.stripe.com/v1/balance", auth=(settings.STRIPE_SECRET_KEY, ""), timeout=20)
                self.stdout.write(f"Stripe API: HTTP {r.status_code}" + (" — klucz działa" if r.ok else f" — {r.json().get('error', {}).get('message', '')[:120]}"))
            except Exception as e:  # noqa: BLE001
                self.stdout.write(f"Stripe API: brak połączenia ({e.__class__.__name__})")
        if settings.ING_API_KEY:
            try:
                import requests

                # an empty body cannot create an invoice: a valid key gets 400 (validation),
                # a wrong one 401/403
                r = requests.post("https://ksiegowosc.ing.pl/v2/api/public/create-invoice", json={},
                                  headers={"ApiUserCompanyRoleKey": settings.ING_API_KEY}, timeout=30)
                verdict = {400: "klucz przyjęty (puste zapytanie odrzucone jako niekompletne — tak ma być)",
                           401: "klucz odrzucony", 403: "klucz odrzucony / brak uprawnień"}.get(r.status_code, "nieoczekiwana odpowiedź")
                self.stdout.write(f"ING API: HTTP {r.status_code} — {verdict}")
                if r.status_code not in (401, 403):
                    self.stdout.write("ING odpowiedź: " + r.text[:400].replace(settings.ING_API_KEY, "***"))
            except Exception as e:  # noqa: BLE001
                self.stdout.write(f"ING API: brak połączenia ({e.__class__.__name__})")
