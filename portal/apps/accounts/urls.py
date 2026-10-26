from django.contrib.auth import views as auth
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"
urlpatterns = [
    path("rejestracja/", views.register, name="register"),
    path("potwierdz/<uidb64>/<token>/", views.confirm_email, name="confirm"),
    path("logowanie/", views.LoginView.as_view(), name="login"),
    path("logowanie/kod/", views.two_factor_check, name="two_factor_check"),
    path("2fa/", views.two_factor_setup, name="two_factor_setup"),
    path("wyloguj/", auth.LogoutView.as_view(), name="logout"),
    path("haslo/", auth.PasswordResetView.as_view(template_name="accounts/password_reset.html", email_template_name="accounts/password_reset_email.txt", subject_template_name="accounts/password_reset_subject.txt", success_url=reverse_lazy("accounts:password_reset_done")), name="password_reset"),
    path("haslo/wyslano/", auth.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("haslo/<uidb64>/<token>/", auth.PasswordResetConfirmView.as_view(template_name="accounts/password_reset_confirm.html", success_url=reverse_lazy("accounts:password_reset_complete")), name="password_reset_confirm"),
    path("haslo/gotowe/", auth.PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"), name="password_reset_complete"),
]
