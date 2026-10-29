import json
import logging
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services
from .forms import BillingForm
from .models import BillingProfile, Invoice

log = logging.getLogger(__name__)


@login_required
def profile(request):
    prof = getattr(request.user, "billing", None)
    initial = {} if prof else {"invoice_email": request.user.email, "kind": "person" if request.user.kind == "person" else "company"}
    form = BillingForm(request.POST or None, instance=prof, initial=initial)
    if request.method == "POST" and form.is_valid():
        p = form.save(commit=False)
        p.user = request.user
        if p.country == "PL" and p.nip and (not prof or prof.nip != p.nip or not p.nip_verified_at):
            res = services.lookup_nip(p.nip)
            if res["ok"]:
                p.nip_verified_at, p.nip_verified_name = timezone.now(), res["name"][:300]
            else:
                p.nip_verified_at, p.nip_verified_name = None, ""
        p.save()
        messages.success(request, "Zapisano dane do faktury.")
        nxt = request.GET.get("next")
        return redirect(nxt if nxt and nxt.startswith("/") else "billing:profile")
    return render(request, "billing/profile.html", {"form": form, "prof": prof, "balance": services.balance(request.user),
                                                    "limit": services.limit_for(request.user), "next": request.GET.get("next", "")})


@login_required
def nip_lookup(request):
    """HTMX: fill the form from the MF register (or VIES for an EU VAT number)."""
    nip = request.GET.get("nip", "")
    res = services.check_vies(nip) if nip[:2].isalpha() else services.lookup_nip(nip)
    return render(request, "billing/_lookup.html", {"res": res})


@login_required
def invoices(request):
    inv = Invoice.objects.filter(user=request.user).exclude(status=Invoice.Status.CANCELLED)
    pending = services.uninvoiced_jobs(request.user).order_by("-finished_at")
    due = sum((i.gross_pln for i in inv if i.status == Invoice.Status.ISSUED), 0)
    return render(request, "billing/invoices.html", {
        "invoices": inv, "pending": pending, "pending_net": sum((j.price_pln for j in pending), 0), "due": due,
        "overdue": [i for i in inv if i.overdue], "prof": getattr(request.user, "billing", None),
        "next_due": min((i.due_date for i in inv if i.status == Invoice.Status.ISSUED and i.due_date), default=None),
        "balance": services.balance(request.user), "limit": services.limit_for(request.user),
    })


def _own_invoice(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    if inv.user_id != request.user.id and not request.user.is_staff:
        raise Http404
    return inv


@login_required
def pay(request, pk):
    inv = _own_invoice(request, pk)
    if inv.status != Invoice.Status.ISSUED:
        messages.info(request, "Ta faktura nie czeka na płatność.")
        return redirect("billing:invoices")
    if not settings.STRIPE_SECRET_KEY:
        messages.error(request, "Płatności online są chwilowo niedostępne — zapłać przelewem.")
        return redirect("billing:invoices")
    base = request.build_absolute_uri("/")[:-1]
    try:
        url = services.stripe_checkout(inv, base + reverse("billing:paid", args=[inv.pk]), base + reverse("billing:invoices"))
    except Exception:  # noqa: BLE001
        log.exception("stripe checkout failed for invoice %s", inv.pk)
        messages.error(request, "Nie udało się otworzyć płatności. Spróbuj za chwilę albo zapłać przelewem.")
        return redirect("billing:invoices")
    return redirect(url)


@login_required
def paid(request, pk):
    inv = _own_invoice(request, pk)
    ok, ref = services.stripe_session_paid(request.GET.get("session_id", "")) if request.GET.get("session_id") else (False, "")
    if ok and ref == str(inv.pk):
        services.mark_paid(inv, "stripe")
        messages.success(request, f"Dziękujemy — faktura {inv.label} jest opłacona.")
    else:
        messages.info(request, "Płatność jest przetwarzana. Status faktury zmieni się, gdy Stripe ją potwierdzi.")
    return redirect("billing:invoices")


@login_required
def pdf(request, pk):
    inv = _own_invoice(request, pk)
    if not inv.pdf or not Path(inv.pdf).is_file():
        if not services.fetch_pdf(inv):
            raise Http404
    return FileResponse(open(inv.pdf, "rb"), as_attachment=True, filename=f"{inv.label.replace('/', '_')}.pdf", content_type="application/pdf")


@csrf_exempt
@require_POST
def stripe_webhook(request):
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret or not services.stripe_verify(request.body, request.headers.get("Stripe-Signature", ""), secret):
        return HttpResponse(status=400)
    event = json.loads(request.body)
    if event.get("type") in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        obj = event["data"]["object"]
        if obj.get("payment_status") == "paid":
            inv = Invoice.objects.filter(pk=(obj.get("metadata") or {}).get("invoice")).first()
            if inv:
                services.mark_paid(inv, "stripe")
    return JsonResponse({"ok": True})


# ----- admin

@staff_member_required
def admin_list(request):
    qs = Invoice.objects.select_related("user").order_by("-created_at")[:300]
    return render(request, "panel/invoices.html", {"invoices": qs, "auto": settings.BILLING["ing_auto_issue"],
                                                   "bank": bool(settings.BILLING["bank_account"]), "ing": bool(settings.ING_API_KEY)})


@staff_member_required
@require_POST
def admin_action(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    action = request.POST.get("action")
    if action == "release":
        inv = services.release(inv)
        if inv.status == Invoice.Status.ISSUED:
            messages.success(request, f"Wystawiono {inv.label} w ING i wysłano do klienta.")
        else:
            messages.error(request, f"ING nie wystawiło faktury: {inv.ing_error[:300]}")
    elif action == "paid":
        services.mark_paid(inv, "przelew (ręcznie)")
        messages.success(request, f"{inv.label} oznaczona jako zapłacona.")
    elif action == "remind" and inv.status == Invoice.Status.ISSUED:
        services.email_invoice(inv, reminder=True)
        messages.success(request, f"Wysłano przypomnienie do {inv.buyer.get('email')}.")
    elif action == "cancel" and inv.status == Invoice.Status.DRAFT:
        inv.jobs.update(invoice=None)
        inv.status = Invoice.Status.CANCELLED
        inv.save(update_fields=["status"])
        messages.success(request, "Projekt anulowany; zlecenia wróciły do niezafakturowanych.")
    return redirect("billing:admin_list")
