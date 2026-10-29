from django.urls import path

from . import views

app_name = "billing"
urlpatterns = [
    path("konto/faktura/", views.profile, name="profile"),
    path("konto/faktura/sprawdz/", views.nip_lookup, name="nip_lookup"),
    path("faktury/", views.invoices, name="invoices"),
    path("faktury/<int:pk>/zaplac/", views.pay, name="pay"),
    path("faktury/<int:pk>/oplacona/", views.paid, name="paid"),
    path("faktury/<int:pk>/pdf/", views.pdf, name="pdf"),
    path("api/stripe/webhook", views.stripe_webhook, name="stripe_webhook"),
    path("panel/faktury/", views.admin_list, name="admin_list"),
    path("panel/faktury/<int:pk>/", views.admin_action, name="admin_action"),
]
