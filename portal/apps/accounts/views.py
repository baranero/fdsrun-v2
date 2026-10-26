from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .forms import RegisterForm
from .models import User


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
