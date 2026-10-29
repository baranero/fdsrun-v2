"""Invoicing data, invoices and the balance rules of decision D-11."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

EU = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "RO", "SE", "SI", "SK"}


class BillingProfile(models.Model):
    class Kind(models.TextChoices):
        COMPANY = "company", "Firma"
        PERSON = "person", "Osoba prywatna"

    class Mode(models.TextChoices):
        PER_JOB = "per_job", "Faktura po każdym zleceniu"
        MONTHLY = "monthly", "Faktura zbiorcza za miesiąc"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="billing")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.COMPANY)
    name = models.CharField("Nazwa firmy albo imię i nazwisko", max_length=200)
    nip = models.CharField("NIP / numer podatkowy", max_length=32, blank=True)
    vat_eu = models.CharField("Numer VAT UE", max_length=20, blank=True)
    street = models.CharField("Ulica i numer", max_length=200)
    postcode = models.CharField("Kod pocztowy", max_length=16)
    city = models.CharField("Miasto", max_length=100)
    country = models.CharField("Kraj (kod ISO)", max_length=2, default="PL")
    invoice_email = models.EmailField("E-mail do faktur")
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.PER_JOB)
    nip_verified_at = models.DateTimeField(null=True, blank=True)
    nip_verified_name = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.nip or self.country})"

    @property
    def is_company(self):
        return self.kind == self.Kind.COMPANY

    @property
    def domestic(self):
        return self.country.upper() == "PL"

    @property
    def tax_treatment(self):
        """(ING taxStake, VAT rate, note) — see docs/faktury-i-vat.md; to confirm with an accountant."""
        c = self.country.upper()
        if c == "PL" or (c in EU and not self.is_company):
            return "TAX_23", Decimal("0.23"), ""
        if c in EU and self.is_company:
            return None, None, "Faktury dla firm z UE wymagają rejestracji VAT-UE usługodawcy (w przygotowaniu)."
        return "TAX_NOT_LIABLE", Decimal("0"), "Usługa niepodlegająca opodatkowaniu w Polsce (art. 28b ustawy o VAT) — odwrotne obciążenie."

    @property
    def can_be_invoiced(self):
        return self.tax_treatment[0] is not None

    @property
    def complete(self):
        need = [self.name, self.street, self.postcode, self.city, self.country, self.invoice_email]
        if self.is_company:
            need.append(self.nip)
        return all(need)


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Projekt"          # created in the portal, not yet in ING
        ISSUED = "issued", "Do zapłaty"      # issued in ING (or released from draft on staging)
        PAID = "paid", "Zapłacona"
        CANCELLED = "cancelled", "Anulowana"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="invoices")
    number = models.CharField(max_length=64, blank=True)
    period = models.CharField(max_length=7, blank=True, help_text="YYYY-MM for a monthly invoice")
    buyer = models.JSONField(default=dict)           # billing data frozen at issue time
    lines = models.JSONField(default=list)           # [{job, name, hours, net}]
    net_pln = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_pln = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_pln = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_stake = models.CharField(max_length=24, blank=True)
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_via = models.CharField(max_length=40, blank=True)
    ing_id = models.CharField(max_length=64, blank=True)
    ing_error = models.TextField(blank=True)
    pdf = models.CharField(max_length=300, blank=True)  # path under JOB_DATA_ROOT/invoices
    stripe_session = models.CharField(max_length=120, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    reminders = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number or f"projekt #{self.pk}"

    @property
    def label(self):
        return self.number or f"Projekt {self.pk}"

    @property
    def overdue(self):
        return self.status == self.Status.ISSUED and self.due_date and self.due_date < timezone.localdate()

    @property
    def open(self):
        return self.status in (self.Status.DRAFT, self.Status.ISSUED)
