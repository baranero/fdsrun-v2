"""Billing rules (decision D-11) and the two outside services: ING Księgowość and Stripe.

Everything that talks to ING or Stripe lives here, so views and tasks stay readable and the
tests can replace these functions.
"""
import datetime as dt
import hashlib
import hmac
import logging
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import requests
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from .models import EU, BillingProfile, Invoice

log = logging.getLogger(__name__)
ING_BASE = "https://ksiegowosc.ing.pl/v2/api/public"
TWO = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- lookups

def lookup_nip(nip: str) -> dict:
    """Polish VAT payer register (biała lista MF). Returns {ok, name, address, status} or {ok: False, error}."""
    nip = re.sub(r"\D", "", nip or "")
    if len(nip) != 10:
        return {"ok": False, "error": "NIP ma 10 cyfr."}
    w = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    if sum(int(a) * b for a, b in zip(nip, w)) % 11 != int(nip[9]):
        return {"ok": False, "error": "Nieprawidłowy NIP (zła cyfra kontrolna)."}
    try:
        r = requests.get(f"https://wl-api.mf.gov.pl/api/search/nip/{nip}", params={"date": timezone.localdate().isoformat()}, timeout=15)
        subj = (r.json().get("result") or {}).get("subject")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Rejestr MF chwilowo nie odpowiada ({e.__class__.__name__}). Możesz zapisać dane bez sprawdzenia."}
    if not subj:
        return {"ok": False, "error": "Nie ma takiego NIP w wykazie podatników VAT."}
    return {"ok": True, "name": subj.get("name", ""), "address": subj.get("workingAddress") or subj.get("residenceAddress") or "", "status": subj.get("statusVat", "")}


def check_vies(vat: str) -> dict:
    vat = re.sub(r"[\s.-]", "", (vat or "").upper())
    cc, num = vat[:2], vat[2:]
    if cc not in EU or not num:
        return {"ok": False, "error": "Numer VAT UE zaczyna się od kodu kraju, np. DE123456789."}
    try:
        r = requests.get(f"https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{num}", timeout=20)
        d = r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"VIES chwilowo nie odpowiada ({e.__class__.__name__})."}
    if not d.get("isValid"):
        return {"ok": False, "error": "VIES nie potwierdza tego numeru."}
    return {"ok": True, "name": d.get("name", ""), "address": d.get("address", "")}


# ---------------------------------------------------------------- balance and limits

def exempt(user) -> bool:
    """Staff run their own test jobs: no invoices, no limits."""
    return user.is_staff


def uninvoiced_jobs(user):
    from apps.jobs.models import Job

    return Job.objects.filter(owner=user, invoice__isnull=True, price_pln__gt=0).exclude(status__in=Job.ACTIVE)


def balance(user) -> Decimal:
    """Unpaid amount (net): open invoices + finished jobs not yet invoiced + running jobs' forecast."""
    from apps.jobs.models import Job

    inv = Invoice.objects.filter(user=user, status__in=[Invoice.Status.DRAFT, Invoice.Status.ISSUED]).aggregate(s=Sum("net_pln"))["s"] or 0
    done = uninvoiced_jobs(user).aggregate(s=Sum("price_pln"))["s"] or 0
    running = sum(j.projected_price_pln for j in Job.objects.filter(owner=user, status__in=Job.ACTIVE))
    return money(inv) + money(done) + money(running)


def limit_for(user):
    """None = no limit (trusted, or at least one paid invoice)."""
    if user.trusted or Invoice.objects.filter(user=user, status=Invoice.Status.PAID).exists():
        return None
    return money(user.per_job_limit_pln or settings.BILLING["balance_limit_pln"])


def can_start(user, est_price) -> tuple[bool, str]:
    if exempt(user):
        return True, ""
    prof = getattr(user, "billing", None)
    if prof is None or not prof.complete:
        return False, "profile"
    if not prof.can_be_invoiced:
        return False, prof.tax_treatment[2]
    overdue = Invoice.objects.filter(user=user, status=Invoice.Status.ISSUED, due_date__lt=timezone.localdate()).first()
    if overdue:
        return False, f"Faktura {overdue.label} jest po terminie płatności — nowe zlecenia są wstrzymane do jej opłacenia. Wyniki możesz pobierać."
    lim = limit_for(user)
    if lim is not None:
        after = balance(user) + money(est_price)
        if after > lim:
            return False, (f"Limit nieopłaconych zleceń dla nowego konta to {lim:.0f} zł netto; z tym zleceniem byłoby {after:.0f} zł. "
                           "Opłać bieżące faktury albo napisz do nas — po pierwszej zapłaconej fakturze limit znika.")
    return True, ""


# ---------------------------------------------------------------- invoices

def _buyer(prof: BillingProfile) -> dict:
    return {"kind": prof.kind, "name": prof.name, "nip": prof.nip, "vat_eu": prof.vat_eu, "street": prof.street,
            "postcode": prof.postcode, "city": prof.city, "country": prof.country.upper(), "email": prof.invoice_email}


@transaction.atomic
def build_invoice(user, jobs, period="") -> Invoice | None:
    """A draft invoice for these finished, priced, not yet invoiced jobs."""
    prof = getattr(user, "billing", None)
    jobs = [j for j in jobs if j.invoice_id is None and j.price_pln > 0]
    if not jobs or prof is None or not prof.can_be_invoiced:
        return None
    stake, rate, note = prof.tax_treatment
    lines = []
    for j in jobs:
        hours = (j.wall_seconds or 0) / 3600
        lines.append({"job": j.public_id, "name": f"Obliczenia FDS: {j.name} ({j.public_id}), {hours:.2f} h, serwer {j.server_type}",
                      "hours": round(hours, 3), "net": str(money(j.price_pln))})
    net = sum(money(line["net"]) for line in lines)
    vat = money(net * rate)
    inv = Invoice.objects.create(user=user, period=period, buyer=_buyer(prof), lines=lines, net_pln=net, vat_pln=vat,
                                 gross_pln=net + vat, tax_stake=stake, note=note)
    from apps.jobs.models import Job

    Job.objects.filter(id__in=[j.id for j in jobs]).update(invoice=inv)
    return inv


def ing_payload(inv: Invoice) -> dict:
    b = inv.buyer
    today = timezone.localdate()
    due = today + dt.timedelta(days=settings.BILLING["payment_days"])
    rate = Decimal("0.23") if inv.tax_stake == "TAX_23" else Decimal("0")
    positions = []
    for line in inv.lines:
        net = money(line["net"])
        tax = money(net * rate)
        positions.append({"name": line["name"][:250], "code": line["job"], "quantity": 1, "unit": "usł.",
                          "net": float(net), "tax": float(tax), "gross": float(net + tax), "taxStake": inv.tax_stake})
    payload = {
        "issuedGross": False,
        "issuePlace": "Grodzisk Mazowiecki",
        "issueDate": today.isoformat(),
        "serviceDate": (today.replace(day=1) - dt.timedelta(days=1)).isoformat() if inv.period else today.isoformat(),
        "description": (inv.note + " " if inv.note else "") + "Płatność: przelew lub online na fdsrun.com.",
        "currency": {"code": "PLN"},
        "payment": {"method": "TRANSFER", "deadlineDate": due.isoformat(), "paidAmount": 0, "splitPayment": False,
                    "bankAccounts": [{"accountNumber": settings.BILLING["bank_account"], "countryCode": "PL"}]},
        "buyer": {"email": b["email"], "fullName": b["name"], "addressStreet": b["street"], "city": b["city"],
                  "postCode": b["postcode"], "countryCode": b["country"], "taxNumber": b.get("nip") or "",
                  "taxCountryCode": b["country"]},
        "positions": positions,
    }
    return payload


def issue_in_ing(inv: Invoice) -> Invoice:
    """Create the invoice in ING Księgowość (a real document, sent on to KSeF by ING) and fetch its PDF."""
    if inv.status != Invoice.Status.DRAFT:
        return inv
    if not settings.ING_API_KEY or not settings.BILLING["bank_account"]:
        inv.ing_error = "Brak klucza ING albo numeru konta firmy (COMPANY_BANK_ACCOUNT)."
        inv.save(update_fields=["ing_error"])
        return inv
    headers = {"ApiUserCompanyRoleKey": settings.ING_API_KEY}
    try:
        r = requests.post(f"{ING_BASE}/create-invoice", json=ing_payload(inv), headers=headers, timeout=60)
    except Exception as e:  # noqa: BLE001
        inv.ing_error = f"ING nie odpowiada: {e}"
        inv.save(update_fields=["ing_error"])
        return inv
    if r.status_code >= 300:
        inv.ing_error = f"HTTP {r.status_code}: {r.text[:1500]}"
        inv.save(update_fields=["ing_error"])
        return inv
    data = r.json() if r.content else {}
    inv.ing_id = str(data.get("id") or data.get("documentId") or "")
    inv.number = str(data.get("number") or data.get("fullNumber") or data.get("documentNumber") or inv.ing_id)
    inv.status = Invoice.Status.ISSUED
    inv.issue_date = timezone.localdate()
    inv.due_date = inv.issue_date + dt.timedelta(days=settings.BILLING["payment_days"])
    inv.ing_error = ""
    inv.save()
    fetch_pdf(inv)
    return inv


def invoice_dir() -> Path:
    d = Path(settings.JOB_DATA_ROOT).parent / "invoices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_pdf(inv: Invoice) -> bool:
    if not inv.ing_id:
        return False
    try:
        r = requests.get(f"{ING_BASE}/download-invoice/{inv.ing_id}/pdf", headers={"ApiUserCompanyRoleKey": settings.ING_API_KEY}, timeout=60)
    except Exception:  # noqa: BLE001
        return False
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        return False
    path = invoice_dir() / f"{re.sub(r'[^A-Za-z0-9_-]', '_', inv.number or str(inv.pk))}.pdf"
    path.write_bytes(r.content)
    inv.pdf = str(path)
    inv.save(update_fields=["pdf"])
    return True


def pay_url(inv: Invoice) -> str:
    return settings.PORTAL_URL.rstrip("/") + reverse("billing:pay", args=[inv.pk])


def email_invoice(inv: Invoice, reminder=False) -> bool:
    b = inv.buyer
    lines = "\n".join(f"  - {line['name']}: {line['net']} zł netto" for line in inv.lines)
    when = inv.due_date.strftime("%d.%m.%Y") if inv.due_date else "—"
    subject = (f"Przypomnienie: faktura {inv.label} — termin minął {when}" if reminder else f"Faktura {inv.label} za obliczenia FDS — {inv.gross_pln} zł")
    body = (
        f"Dzień dobry,\n\n{'przypominamy o płatności za fakturę' if reminder else 'w załączniku faktura'} {inv.label}"
        f"{' za ' + inv.period if inv.period else ''}.\n\n{lines}\n\n"
        f"Razem: {inv.net_pln} zł netto, {inv.vat_pln} zł VAT, {inv.gross_pln} zł brutto.\nTermin płatności: {when}.\n\n"
        f"Zapłać online (karta, BLIK, Przelewy24 i inne): {pay_url(inv)}\n"
        f"Albo przelewem: {settings.COMPANY['name']}, konto {settings.BILLING['bank_account']}, tytuł: {inv.label}.\n\n"
        f"Wyniki obliczeń są dostępne w portalu przez {settings.PRICING['results_days']} dni od zakończenia.\n\n"
        f"{settings.COMPANY['name']}, {settings.COMPANY['address']}, NIP {settings.COMPANY['nip']}\n"
    )
    msg = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [b["email"]], reply_to=[settings.COMPANY["email"]])
    if inv.pdf and Path(inv.pdf).is_file():
        msg.attach_file(inv.pdf, "application/pdf")
    try:
        msg.send()
    except Exception:  # noqa: BLE001
        log.exception("invoice e-mail failed for %s", inv.pk)
        return False
    if reminder:
        inv.reminders += 1
        inv.save(update_fields=["reminders"])
    else:
        inv.emailed_at = timezone.now()
        inv.save(update_fields=["emailed_at"])
    return True


def release(inv: Invoice) -> Invoice:
    """Issue in ING and e-mail the client (admin button, or automatically when ING_AUTO_ISSUE=1)."""
    inv = issue_in_ing(inv)
    if inv.status == Invoice.Status.ISSUED and not inv.emailed_at:
        email_invoice(inv)
    return inv


def mark_paid(inv: Invoice, via: str) -> Invoice:
    if inv.status in (Invoice.Status.ISSUED, Invoice.Status.DRAFT):
        inv.status = Invoice.Status.PAID
        inv.paid_at = timezone.now()
        inv.paid_via = via[:40]
        inv.save(update_fields=["status", "paid_at", "paid_via"])
    return inv


# ---------------------------------------------------------------- Stripe (REST, no SDK)

def stripe_checkout(inv: Invoice, success_url: str, cancel_url: str) -> str:
    """A Checkout Session for the invoice's gross amount. Payment methods are whatever is enabled
    in the Stripe dashboard (card, BLIK, Przelewy24, wallets…) — decision D-11."""
    amount = int((inv.gross_pln * 100).to_integral_value())
    data = {
        "mode": "payment",
        "line_items[0][quantity]": 1,
        "line_items[0][price_data][currency]": "pln",
        "line_items[0][price_data][unit_amount]": amount,
        "line_items[0][price_data][product_data][name]": f"Faktura {inv.label} — obliczenia FDS",
        "customer_email": inv.buyer.get("email", ""),
        "success_url": success_url + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": cancel_url,
        "metadata[invoice]": inv.pk,
        "payment_intent_data[metadata][invoice]": inv.pk,
        "locale": "pl" if inv.buyer.get("country", "PL") == "PL" else "en",
    }
    r = requests.post("https://api.stripe.com/v1/checkout/sessions", data=data, auth=(settings.STRIPE_SECRET_KEY, ""), timeout=30)
    r.raise_for_status()
    s = r.json()
    inv.stripe_session = s["id"]
    inv.save(update_fields=["stripe_session"])
    return s["url"]


def stripe_session_paid(session_id: str) -> tuple[bool, str]:
    r = requests.get(f"https://api.stripe.com/v1/checkout/sessions/{session_id}", auth=(settings.STRIPE_SECRET_KEY, ""), timeout=30)
    if r.status_code != 200:
        return False, ""
    s = r.json()
    return s.get("payment_status") == "paid", str((s.get("metadata") or {}).get("invoice", ""))


def stripe_verify(payload: bytes, header: str, secret: str, tolerance=300) -> bool:
    """Stripe-Signature: t=…,v1=… — HMAC-SHA256 of 't.payload' with the webhook secret."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(timezone.now().timestamp() - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    sigs = [v for k, v in (p.split("=", 1) for p in header.split(",")) if k == "v1"]
    return any(hmac.compare_digest(expected, s) for s in sigs)


# ---------------------------------------------------------------- scheduled work

def invoice_finished_job(job):
    """Called when a job's final price is known."""
    user = job.owner
    if exempt(user) or job.price_pln <= 0:
        return None
    prof = getattr(user, "billing", None)
    if prof is None or prof.mode != BillingProfile.Mode.PER_JOB:
        return None
    inv = build_invoice(user, [job])
    if inv and settings.BILLING["ing_auto_issue"]:
        release(inv)
    return inv


def monthly_run(today=None):
    """1st of the month: one invoice per monthly-mode client for last month's jobs."""
    today = today or timezone.localdate()
    last = today.replace(day=1) - dt.timedelta(days=1)
    period = last.strftime("%Y-%m")
    made = []
    for prof in BillingProfile.objects.filter(mode=BillingProfile.Mode.MONTHLY).select_related("user"):
        if exempt(prof.user):
            continue
        jobs = list(uninvoiced_jobs(prof.user).filter(Q(finished_at__date__lte=last)))
        inv = build_invoice(prof.user, jobs, period=period)
        if inv:
            made.append(inv)
            if settings.BILLING["ing_auto_issue"]:
                release(inv)
    return made


def remind_overdue(today=None):
    today = today or timezone.localdate()
    sent = 0
    for inv in Invoice.objects.filter(status=Invoice.Status.ISSUED, due_date__lt=today):
        days = (today - inv.due_date).days
        if (days >= 1 and inv.reminders == 0) or (days >= 7 and inv.reminders == 1):
            sent += email_invoice(inv, reminder=True)
    return sent
