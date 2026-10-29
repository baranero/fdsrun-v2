import datetime as dt
import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.jobs.models import Job

from . import services
from .models import BillingProfile, Invoice


def profile(user, **kw):
    d = dict(user=user, kind="company", name="Biuro X", nip="6182094888", street="Grzybowa 7A/2", postcode="05-825",
             city="Grodzisk Mazowiecki", country="PL", invoice_email="faktury@x.pl")
    d.update(kw)
    return BillingProfile.objects.create(**d)


def done_job(user, price, **kw):
    j = Job(owner=user, name=kw.pop("name", "m"), filename="m.fds", status=Job.Status.DONE, price_pln=price,
            wall_seconds=3600, server_type="cpx42", finished_at=kw.pop("finished_at", timezone.now()), **kw)
    j.save()
    return j


class RulesTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(email="k@x.pl", password="x", kind="company")

    def test_nip_checksum(self):
        self.assertFalse(services.lookup_nip("1234567890")["ok"])
        self.assertIn("cyfr", services.lookup_nip("123")["error"])

    def test_start_requires_profile_then_limit_then_overdue(self):
        self.assertEqual(services.can_start(self.u, 10), (False, "profile"))
        profile(self.u)
        self.assertTrue(services.can_start(self.u, 400)[0])
        done_job(self.u, 300)
        ok, why = services.can_start(self.u, 250)          # 300 open + 250 > 500
        self.assertFalse(ok)
        self.assertIn("500", why)
        self.u.trusted = True
        self.u.save()
        self.assertTrue(services.can_start(self.u, 250)[0])
        Invoice.objects.create(user=self.u, status=Invoice.Status.ISSUED, net_pln=1, gross_pln=1, due_date=timezone.localdate() - dt.timedelta(days=1))
        ok, why = services.can_start(self.u, 1)
        self.assertFalse(ok)
        self.assertIn("po terminie", why)

    def test_limit_disappears_after_first_paid_invoice(self):
        profile(self.u)
        Invoice.objects.create(user=self.u, status=Invoice.Status.PAID, net_pln=10, gross_pln=12.3)
        done_job(self.u, 900)
        self.assertTrue(services.can_start(self.u, 900)[0])

    def test_staff_exempt(self):
        self.u.is_staff = True
        self.assertEqual(services.can_start(self.u, 99999), (True, ""))

    def test_tax_treatment(self):
        pl = profile(self.u)
        self.assertEqual(pl.tax_treatment[0], "TAX_23")
        pl.country, pl.kind = "DE", "company"
        self.assertIsNone(pl.tax_treatment[0])        # EU company: needs VAT-UE registration
        pl.kind = "person"
        self.assertEqual(pl.tax_treatment[0], "TAX_23")
        pl.country, pl.kind = "US", "company"
        self.assertEqual(pl.tax_treatment[0], "TAX_NOT_LIABLE")


class InvoiceTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(email="k@x.pl", password="x", kind="company")

    def test_per_job_invoice_draft(self):
        profile(self.u)
        j = done_job(self.u, 100.0)
        inv = services.invoice_finished_job(j)
        self.assertEqual(inv.status, Invoice.Status.DRAFT)
        self.assertEqual((inv.net_pln, inv.vat_pln, inv.gross_pln), (Decimal("100.00"), Decimal("23.00"), Decimal("123.00")))
        j.refresh_from_db()
        self.assertEqual(j.invoice_id, inv.pk)
        self.assertIsNone(services.invoice_finished_job(j))   # never twice

    def test_monthly_run_groups_last_month(self):
        profile(self.u, mode="monthly")
        today = dt.date(2026, 11, 1)
        oct_ = timezone.make_aware(dt.datetime(2026, 10, 15, 12))
        done_job(self.u, 50, name="a", finished_at=oct_)
        done_job(self.u, 70, name="b", finished_at=oct_)
        self.assertIsNone(services.invoice_finished_job(Job.objects.first()))  # monthly: nothing per job
        made = services.monthly_run(today)
        self.assertEqual(len(made), 1)
        self.assertEqual((made[0].period, made[0].net_pln, len(made[0].lines)), ("2026-10", Decimal("120.00"), 2))

    @override_settings(ING_API_KEY="k", BILLING={"balance_limit_pln": 500, "payment_days": 14, "bank_account": "11 1050 0000 0000 0000 0000 0000", "ing_auto_issue": False})
    def test_release_sends_to_ing_and_mails(self):
        from django.core import mail

        profile(self.u)
        inv = services.invoice_finished_job(done_job(self.u, 100))
        resp = mock.Mock(status_code=201, content=b"{}")
        resp.json.return_value = {"id": 4711, "number": "FV/2026/11/0001"}
        with mock.patch("apps.billing.services.requests.post", return_value=resp) as post, mock.patch("apps.billing.services.fetch_pdf", return_value=False):
            services.release(inv)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["buyer"]["taxNumber"], "6182094888")
        self.assertEqual(body["positions"][0]["taxStake"], "TAX_23")
        self.assertEqual(body["payment"]["bankAccounts"][0]["accountNumber"], "11 1050 0000 0000 0000 0000 0000")
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.number), (Invoice.Status.ISSUED, "FV/2026/11/0001"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/faktury/", mail.outbox[0].body)

    def test_overdue_reminders_twice(self):
        inv = Invoice.objects.create(user=self.u, status=Invoice.Status.ISSUED, number="FV/1", net_pln=1, gross_pln=1,
                                     buyer={"email": "f@x.pl", "name": "X"}, due_date=dt.date(2026, 11, 1))
        self.assertEqual(services.remind_overdue(dt.date(2026, 11, 2)), 1)
        self.assertEqual(services.remind_overdue(dt.date(2026, 11, 3)), 0)
        self.assertEqual(services.remind_overdue(dt.date(2026, 11, 8)), 1)
        inv.refresh_from_db()
        self.assertEqual(inv.reminders, 2)


@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
class StripeTests(TestCase):
    def test_webhook_marks_paid(self):
        u = User.objects.create_user(email="k@x.pl", password="x")
        inv = Invoice.objects.create(user=u, status=Invoice.Status.ISSUED, net_pln=1, gross_pln=1)
        payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {"payment_status": "paid", "metadata": {"invoice": str(inv.pk)}}}}).encode()
        t = int(time.time())
        sig = hmac.new(b"whsec_test", f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
        self.assertEqual(self.client.post(reverse("billing:stripe_webhook"), payload, content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=bad").status_code, 400)
        r = self.client.post(reverse("billing:stripe_webhook"), payload, content_type="application/json", HTTP_STRIPE_SIGNATURE=f"t={t},v1={sig}")
        self.assertEqual(r.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PAID)


class ViewTests(TestCase):
    def test_profile_and_start_gate(self):
        u = User.objects.create_user(email="k@x.pl", password="x", kind="company")
        self.client.login(username="k@x.pl", password="x")
        job = Job(owner=u, name="m", filename="m.fds", analysis={"advice": {"options": [{"procs": 1, "server": "cpx32", "hours": 1, "costEur": 0.1, "pricePln": 5}], "best": []}, "issues": []})
        job.save()
        with override_settings(EMAIL_HOST=""):
            r = self.client.post(reverse("jobs:start", args=[job.public_id]), {"procs": 1, "server_type": "cpx32"})
        self.assertIn(reverse("billing:profile"), r["Location"])
        with mock.patch("apps.billing.services.lookup_nip", return_value={"ok": True, "name": "FP", "address": ""}):
            r = self.client.post(reverse("billing:profile"), {"kind": "company", "name": "FP", "nip": "618-209-48-88", "street": "Grzybowa 7A/2",
                                                                "postcode": "05-825", "city": "Grodzisk", "country": "PL", "invoice_email": "f@x.pl", "mode": "monthly"})
        self.assertEqual(r.status_code, 302)
        p = BillingProfile.objects.get(user=u)
        self.assertEqual((p.nip, p.mode), ("6182094888", "monthly"))
        self.assertIsNotNone(p.nip_verified_at)
        self.assertContains(self.client.get(reverse("billing:invoices")), "Nie masz jeszcze faktur")
