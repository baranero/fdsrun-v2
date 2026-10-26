from django.contrib.auth import views as auth
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("rejestracja/", views.register, name="register"),
    path("logowanie/", auth.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("wyloguj/", auth.LogoutView.as_view(), name="logout"),
]
