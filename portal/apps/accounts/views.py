from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.views.decorators.http import require_http_methods

from . import twofactor
from .forms import RegisterForm
from .models import User


class LoginView(DjangoLoginView):
    """Password first; if the account has 2FA, hold the session until the code is right."""

    template_name = "accounts/login.html"

    def form_valid(self, form):
        user = form.get_user()
        if user.two_factor_enabled:
            self.request.session["pre_2fa_user"] = user.pk
            self.request.session["pre_2fa_next"] = self.get_success_url()
            return redirect("accounts:two_factor_check")
        return super().form_valid(form)


@require_http_methods(["GET", "POST"])
def two_factor_check(request):
    uid = request.session.get("pre_2fa_user")
    if not uid:
        return redirect("accounts:login")
    user = User.objects.filter(pk=uid).first()
    error = ""
    if request.method == "POST" and user:
        code = request.POST.get("code", "")
        if twofactor.verify(user.totp_secret, code) or twofactor.use_backup_code(user, code):
            nxt = request.session.pop("pre_2fa_next", None) or reverse("jobs:list")
            request.session.pop("pre_2fa_user", None)
            login(request, user)
            return redirect(nxt)
        error = "Nieprawidłowy kod. Sprawdź czas w telefonie i spróbuj ponownie."
    return render(request, "accounts/two_factor_check.html", {"error": error})


@login_required
def two_factor_setup(request):
    user = request.user
    if request.method == "POST" and request.POST.get("action") == "disable":
        if authenticate(request, username=user.email, password=request.POST.get("password", "")):
            user.totp_secret, user.totp_backup = "", ""
            user.save(update_fields=["totp_secret", "totp_backup"])
            messages.info(request, "Logowanie dwuetapowe wyłączone.")
        else:
            messages.error(request, "Błędne hasło.")
        return redirect("accounts:two_factor_setup")
    if user.two_factor_enabled:
        return render(request, "accounts/two_factor_setup.html", {"enabled": True})
    secret = request.session.get("totp_setup_secret") or twofactor.new_secret()
    request.session["totp_setup_secret"] = secret
    ctx = {"enabled": False, "secret": secret, "qr": twofactor.qr_svg_data_uri(twofactor.provisioning_uri(user, secret))}
    if request.method == "POST":
        if twofactor.verify(secret, request.POST.get("code", "")):
            codes = twofactor.make_backup_codes()
            user.totp_secret = secret
            user.totp_backup = ",".join(twofactor.hash_code(c) for c in codes)
            user.save(update_fields=["totp_secret", "totp_backup"])
            request.session.pop("totp_setup_secret", None)
            return render(request, "accounts/two_factor_setup.html", {"enabled": True, "backup_codes": codes})
        ctx["error"] = "Kod się nie zgadza. Zeskanuj kod QR jeszcze raz i wpisz aktualny kod z aplikacji."
    return render(request, "accounts/two_factor_setup.html", ctx)


def register(request):
    if request.user.is_authenticated:
        return redirect("jobs:list")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)          # login first: the token depends on last_login
        send_confirmation(user)
        messages.info(request, "Konto założone. Wysłaliśmy e-mail z linkiem potwierdzającym adres — kliknij go, żeby uruchamiać obliczenia.")
        return redirect("jobs:list")
    return render(request, "accounts/register.html", {"form": form})


def send_confirmation(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    url = settings.PORTAL_URL + reverse("accounts:confirm", args=[uid, token])
    body = f"Dzień dobry,\n\npotwierdź adres e-mail w fdsrun, klikając w link:\n{url}\n\nJeśli to nie Ty zakładałeś konto, zignoruj tę wiadomość.\n\nfdsrun"
    try:
        send_mail("Potwierdź adres e-mail w fdsrun", body, settings.DEFAULT_FROM_EMAIL, [user.email])
    except Exception:  # noqa: BLE001
        pass


def confirm_email(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError):
        user = None
    if user and default_token_generator.check_token(user, token):
        if not user.email_confirmed:
            user.email_confirmed = True
            user.save(update_fields=["email_confirmed"])
        messages.success(request, "Adres e-mail potwierdzony.")
        return redirect("jobs:list")
    messages.error(request, "Link potwierdzający jest nieprawidłowy lub wygasł.")
    return redirect("home")
