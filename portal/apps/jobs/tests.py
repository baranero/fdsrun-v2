import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.compute.models import Machine

from .models import Job

MINIMAL_FDS = """&HEAD CHID='test', TITLE='test'/
&TIME T_END=10.0/
&DUMP DT_RESTART=300.0/
&MESH ID='M1', IJK=20,20,20, XB=0,2,0,2,0,2, MPI_PROCESS=0/
&MESH ID='M2', IJK=20,20,20, XB=2,4,0,2,0,2, MPI_PROCESS=1/
&REAC FUEL='ETHANOL', SOOT_YIELD=0.05/
&SURF ID='FIRE', HRRPUA=500.0/
&VENT XB=0.5,1.5,0.5,1.5,0,0, SURF_ID='FIRE'/
&VENT XB=4,4,0,2,0,2, SURF_ID='OPEN'/
&DEVC ID='T1', QUANTITY='TEMPERATURE', XYZ=1,1,1.8/
&TAIL /
"""

BROKEN_FDS = MINIMAL_FDS.replace("&TAIL /", "").replace("SURF_ID='FIRE'/", "SURF_ID='MISSING'/")

TMP = tempfile.mkdtemp(prefix="fdsrun-test-")


@override_settings(JOB_DATA_ROOT=Path(TMP), CELERY_TASK_ALWAYS_EAGER=True, HCLOUD_TOKEN="test-token")
class JobFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user("inz@example.com", "haslo-bardzo-tajne", email_confirmed=True)
        self.client.login(username="inz@example.com", password="haslo-bardzo-tajne")

    def upload(self, text=MINIMAL_FDS, name="model.fds"):
        resp = self.client.post(reverse("jobs:new"), {"file": SimpleUploadedFile(name, text.encode())})
        self.assertEqual(resp.status_code, 302, resp.content[:500])
        return Job.objects.get(owner=self.user)

    def test_upload_analyzes_and_prices(self):
        job = self.upload()
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertEqual(job.chid, "test")
        self.assertEqual(job.total_cells, 16000)
        self.assertEqual(job.n_meshes, 2)
        self.assertGreater(job.est_hours, 0)
        self.assertGreater(job.est_price_pln, 0)
        self.assertTrue(job.input_path.exists())
        page = self.client.get(reverse("jobs:detail", args=[job.public_id]))
        self.assertContains(page, "Uruchom obliczenia")

    def test_broken_file_cannot_start(self):
        job = self.upload(BROKEN_FDS)
        levels = {i["code"] for i in job.analysis["issues"]}
        self.assertIn("NO_TAIL", levels)
        self.assertIn("BAD_REF", levels)
        resp = self.client.post(reverse("jobs:start", args=[job.public_id]), {"procs": 2, "server_type": "cpx32"})
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.DRAFT)
        self.assertEqual(resp.status_code, 302)

    def test_rejects_non_fds(self):
        resp = self.client.post(reverse("jobs:new"), {"file": SimpleUploadedFile("x.txt", b"hello")})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Job.objects.count(), 0)

    def test_other_users_cannot_see_job(self):
        job = self.upload()
        User.objects.create_user("obcy@example.com", "inne-tajne-haslo")
        self.client.login(username="obcy@example.com", password="inne-tajne-haslo")
        self.assertEqual(self.client.get(reverse("jobs:detail", args=[job.public_id])).status_code, 404)

    @mock.patch("apps.compute.hcloud_client.delete_server", return_value=True)
    @mock.patch("apps.compute.hcloud_client.create_server", return_value=(4242, "10.0.0.5"))
    def test_full_run_through_agent_api(self, create_server, delete_server):
        job = self.upload()
        opt = job.analysis["advice"]["options"][0]
        resp = self.client.post(reverse("jobs:start", args=[job.public_id]), {"procs": opt["procs"], "server_type": opt["server"]})
        self.assertEqual(resp.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.PROVISIONING)
        create_server.assert_called_once()
        run_text = job.run_path.read_text()
        self.assertEqual(run_text.count("MPI_PROCESS="), 2)
        self.assertIn(f"MPI_PROCESS={opt['procs'] - 1}", run_text)
        machine = Machine.objects.get(job=job)
        self.assertEqual(machine.hcloud_id, 4242)

        # cloud-init carries the agent and the job token
        from apps.compute.hcloud_client import user_data
        ud = user_data(job)
        self.assertIn(job.agent_token, ud)
        self.assertIn("fdsrun-agent.service", ud)
        self.assertIn("def main():", ud)

        auth = {"HTTP_AUTHORIZATION": f"Bearer {job.agent_token}"}
        bad = self.client.get(reverse("compute:spec", args=[job.public_id]), HTTP_AUTHORIZATION="Bearer wrong")
        self.assertEqual(bad.status_code, 403)
        spec = self.client.get(reverse("compute:spec", args=[job.public_id]), **auth).json()
        self.assertEqual(spec["procs"], opt["procs"])
        self.assertEqual(self.client.get(reverse("compute:input", args=[job.public_id]), **auth).status_code, 200)

        # progress inside the test window, then past it
        r = self.client.post(reverse("compute:progress", args=[job.public_id]), json.dumps({"phase": "running", "step": 100, "t": 1.0, "dt": 0.01, "wall_s": 50, "out_tail": "Time Step: 100"}), content_type="application/json", **auth)
        self.assertEqual(r.json()["action"], "continue")
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.TESTING)
        self.client.post(reverse("compute:progress", args=[job.public_id]), json.dumps({"phase": "running", "step": 500, "t": 5.0, "dt": 0.01, "wall_s": 200}), content_type="application/json", **auth)
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.RUNNING)
        self.assertEqual(job.progress_pct, 50)
        self.assertIsNotNone(job.eta_hours)

        # result upload and finish
        r = self.client.post(reverse("compute:upload", args=[job.public_id, "test_devc.csv"]), data=b"Time,T1\n0,20\n", content_type="application/octet-stream", **auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.post(reverse("compute:upload", args=[job.public_id, "evil name"]), data=b"x", content_type="application/octet-stream", **auth).status_code, 400)
        self.assertIn(self.client.post(f"/api/compute/jobs/{job.public_id}/files/..%2Fevil", data=b"x", content_type="application/octet-stream", **auth).status_code, (400, 404))
        self.client.post(reverse("compute:finish", args=[job.public_id]), json.dumps({"status": "done", "message": "ok", "wall_s": 400}), content_type="application/json", **auth)
        job.refresh_from_db()
        machine.refresh_from_db()
        self.assertEqual(job.status, Job.Status.DONE)
        self.assertEqual(machine.status, Machine.Status.DELETED)
        delete_server.assert_called_once_with(4242)
        self.assertGreater(job.cost_eur, 0)
        self.assertIsNotNone(job.expires_at)

        # owner can download, agent token no longer accepted for progress
        self.assertEqual(self.client.get(reverse("jobs:file", args=[job.public_id, "test_devc.csv"]), follow=True).status_code, 200)
        r = self.client.post(reverse("compute:progress", args=[job.public_id]), json.dumps({"phase": "running"}), content_type="application/json", **auth)
        self.assertEqual(r.json()["action"], "stop")

    @mock.patch("apps.compute.hcloud_client.list_app_servers", return_value=[])
    @mock.patch("apps.compute.hcloud_client.delete_server", return_value=True)
    @mock.patch("apps.compute.hcloud_client.create_server", return_value=(7, "10.0.0.7"))
    def test_watchdog_kills_stalled_job(self, create_server, delete_server, list_servers):
        from django.utils import timezone

        from apps.compute.tasks import watchdog

        job = self.upload()
        opt = job.analysis["advice"]["options"][0]
        self.client.post(reverse("jobs:start", args=[job.public_id]), {"procs": opt["procs"], "server_type": opt["server"]})
        Job.objects.filter(id=job.id).update(status=Job.Status.RUNNING, last_heartbeat=timezone.now() - timezone.timedelta(hours=1))
        watchdog()
        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.STALLED)
        delete_server.assert_called_once_with(7)


class ChartTests(TestCase):
    def test_hrr_and_devc_parse(self):
        from pathlib import Path

        from . import charts

        d = Path(TMP) / "charts"
        d.mkdir(parents=True, exist_ok=True)
        (d / "x_hrr.csv").write_text("s,kW,kW,kW\nTime,HRR,Q_RADI,Q_CONV\n0,0,0,0\n2,10,-3,-7\n4,20,-6,-14\n6,30,-9,-21,broken\n")
        (d / "x_devc.csv").write_text("s,C,C,m\nTime,T1,T2,VIS\n0,20,20,30\n2,25,21,29.5\n")
        hrr = charts.hrr_series(d, "x")
        self.assertEqual([s["name"] for s in hrr], ["HRR", "Q_RADI", "Q_CONV"])
        self.assertEqual(hrr[0]["last"], 20)  # broken trailing line skipped
        devc = charts.devc_series(d, "x")
        self.assertEqual(set(devc), {"C", "m"})
        self.assertEqual(len(devc["C"]), 2)
        self.assertEqual(charts.hrr_series(d, "missing"), [])


class AccountTests(TestCase):
    def test_register_sends_confirmation_and_start_requires_it(self):
        from django.core import mail

        resp = self.client.post(reverse("accounts:register"), {"email": "nowy@example.com", "kind": "company", "password1": "Trudne-haslo-123", "password2": "Trudne-haslo-123"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/konto/potwierdz/", mail.outbox[0].body)
        link = [l for l in mail.outbox[0].body.splitlines() if "/konto/potwierdz/" in l][0]
        path = link[link.index("/konto/"):]
        user = User.objects.get(email="nowy@example.com")
        self.assertFalse(user.email_confirmed)
        self.assertEqual(self.client.get(path).status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.email_confirmed)

    def test_password_reset_mail(self):
        from django.core import mail

        User.objects.create_user("x@example.com", "haslo-bardzo-tajne")
        self.client.post(reverse("accounts:password_reset"), {"email": "x@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/konto/haslo/", mail.outbox[0].body)


class TwoFactorTests(TestCase):
    def test_setup_and_login_with_code(self):
        import pyotp

        from apps.accounts import twofactor

        user = User.objects.create_user("tf@example.com", "haslo-bardzo-tajne", email_confirmed=True)
        self.client.login(username="tf@example.com", password="haslo-bardzo-tajne")
        page = self.client.get(reverse("accounts:two_factor_setup"))
        self.assertContains(page, "data:image/svg+xml")
        secret = self.client.session["totp_setup_secret"]
        self.assertContains(self.client.post(reverse("accounts:two_factor_setup"), {"code": "000000"}), "nie zgadza")
        resp = self.client.post(reverse("accounts:two_factor_setup"), {"code": pyotp.TOTP(secret).now()})
        self.assertContains(resp, "kody zapasowe")
        user.refresh_from_db()
        self.assertTrue(user.two_factor_enabled)
        self.client.logout()
        # password alone is not enough any more
        resp = self.client.post(reverse("accounts:login"), {"username": "tf@example.com", "password": "haslo-bardzo-tajne"})
        self.assertRedirects(resp, reverse("accounts:two_factor_check"))
        self.assertEqual(self.client.get(reverse("jobs:list")).status_code, 302)
        resp = self.client.post(reverse("accounts:two_factor_check"), {"code": "123456"})
        self.assertContains(resp, "Nieprawidłowy")
        resp = self.client.post(reverse("accounts:two_factor_check"), {"code": pyotp.TOTP(secret).now()})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.get(reverse("jobs:list")).status_code, 200)
        self.assertTrue(twofactor.verify(secret, pyotp.TOTP(secret).now()))


class NewScreensTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(email="s@example.com", password="x", kind="company")
        self.client.login(username="s@example.com", password="x")

    def test_dashboard_and_list_render(self):
        self.assertContains(self.client.get(reverse("jobs:dashboard")), "Pulpit")
        self.assertContains(self.client.get(reverse("jobs:list") + "?f=active&q=abc"), "Nic nie pasuje")

    def test_console_and_pricing(self):
        job = Job(owner=self.user, name="m", filename="m.fds", chid="m", status=Job.Status.RUNNING, out_tail=" Time Step: 1, Simulation Time: 0.1 s")
        job.save()
        r = self.client.get(reverse("jobs:console", args=[job.public_id]))
        self.assertContains(r, "Time Step")
        self.assertContains(self.client.get(reverse("legal:pricing")), "Cennik")


class DownloadTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(JOB_DATA_ROOT=self.tmp)
        self.override.enable()
        self.user = get_user_model().objects.create_user(email="d@example.com", password="x", kind="company")
        self.other = get_user_model().objects.create_user(email="o@example.com", password="x", kind="company")
        self.job = Job(owner=self.user, name="m", filename="m.fds", chid="m", status=Job.Status.DONE)
        self.job.save()
        self.job.results_dir.mkdir(parents=True)
        (self.job.results_dir / "m_hrr.csv").write_text("a,b\n1,2\n")
        (self.job.results_dir / "m.smv").write_bytes(b"x" * 5000)
        (self.job.results_dir / "m.out").write_text("ok\n")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_archives_and_downloads(self):
        from apps.jobs import archives

        self.assertEqual(archives.build_archives(self.job), 3)
        names = [a["key"] for a in archives.archive_files(self.job)]
        self.assertEqual(names, ["csv", "smokeview", "all"])
        self.client.login(username="d@example.com", password="x")
        url = reverse("download", args=[self.job.public_id, "m.smv"])
        r = self.client.get(url, HTTP_RANGE="bytes=100-199")
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r["Content-Range"], "bytes 100-199/5000")
        self.assertEqual(len(b"".join(r.streaming_content)), 100)
        self.assertEqual(self.client.get(reverse("download", args=[self.job.public_id, "m_all.zip"])).status_code, 200)
        # forward_auth answer for Caddy
        r = self.client.get(reverse("download_auth"), HTTP_X_FORWARDED_URI=f"/pobierz/{self.job.public_id}/m_all.zip")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Fdsrun-Path"], f"/{self.job.public_id}/archives/m_all.zip")
        self.assertEqual(self.client.get(reverse("download_auth"), HTTP_X_FORWARDED_URI=f"/pobierz/{self.job.public_id}/../x").status_code, 404)
        # another user: no
        self.client.login(username="o@example.com", password="x")
        self.assertEqual(self.client.get(url).status_code, 403)
        # signed link: yes, without login
        self.client.logout()
        signed = archives.download_url(self.job, "m_csv.zip", signed=True)
        self.assertEqual(self.client.get(signed).status_code, 200)
        self.assertEqual(self.client.get(reverse("download_auth"), HTTP_X_FORWARDED_URI=signed).status_code, 200)
        self.assertEqual(self.client.get(signed.replace("?t=", "?t=x")).status_code, 403)
        # share fragment for the owner
        self.client.login(username="d@example.com", password="x")
        self.assertContains(self.client.get(reverse("jobs:share", args=[self.job.public_id])), "curl -L -C -")


class ProjectTests(TestCase):
    def test_upload_with_project_and_edit(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(email="p@example.com", password="x", kind="company")
        self.client.login(username="p@example.com", password="x")
        job = Job(owner=user, name="m", filename="m.fds", chid="m")
        job.save()
        r = self.client.post(reverse("jobs:edit", args=[job.public_id]), {"name": "Klatka D", "project": "Biurowiec", "note": "wariant 2"})
        self.assertEqual(r.status_code, 302)
        job.refresh_from_db()
        self.assertEqual((job.name, job.project.name, job.note), ("Klatka D", "Biurowiec", "wariant 2"))
        self.assertContains(self.client.get(reverse("jobs:list") + "?p=Biurowiec"), "Klatka D")
        self.assertNotContains(self.client.get(reverse("jobs:list") + "?p=none"), "Klatka D")


@override_settings(SOCIAL_PROVIDERS_ENABLED=["google"], SOCIALACCOUNT_PROVIDERS={"google": {"APPS": [{"client_id": "x", "secret": "y"}], "SCOPE": ["email"]}})
class SocialLoginTests(TestCase):
    def test_buttons_and_redirect_to_provider(self):
        r = self.client.get(reverse("accounts:login"))
        self.assertContains(r, "Kontynuuj z Google")
        self.assertNotContains(r, "Kontynuuj z GitHub")
        r = self.client.post(reverse("google_login"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("accounts.google.com", r["Location"])


class LiveFilesTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(JOB_DATA_ROOT=self.tmp)
        self.override.enable()
        self.user = get_user_model().objects.create_user(email="l@example.com", password="x", kind="company")
        self.job = Job(owner=self.user, name="m", filename="m.fds", chid="m", status=Job.Status.RUNNING)
        self.job.save()
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {self.job.agent_token}"}

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _post(self, name, data, offset=None, head=None):
        import hashlib

        url = f"/api/compute/jobs/{self.job.public_id}/files/{name}" + (f"?offset={offset}" if offset is not None else "")
        extra = dict(self.auth)
        if head is not None:
            extra["HTTP_X_HEAD_SHA256"] = hashlib.sha256(head[:65536]).hexdigest()
        return self.client.post(url, data=data, content_type="application/octet-stream", **extra)

    def test_append_protocol(self):
        a, b = b"A" * 100_000, b"B" * 50_000
        self.assertEqual(self._post("m_01.sf", a, offset=0).json()["size"], 100_000)
        self.assertEqual(self._post("m_01.sf", b, offset=100_000, head=a).json()["size"], 150_000)
        self.assertEqual((self.job.results_dir / "m_01.sf").read_bytes(), a + b)
        # wrong offset: portal tells its size
        r = self._post("m_01.sf", b, offset=120_000, head=a)
        self.assertEqual((r.status_code, r.json()["size"]), (409, 150_000))
        # same size but a different start (file rewritten): restart from 0
        r = self._post("m_01.sf", b, offset=150_000, head=b"C" * 70_000)
        self.assertEqual((r.status_code, r.json()["size"]), (409, 0))
        self.job.refresh_from_db()
        self.assertIsNotNone(self.job.files_synced_at)

    def test_sync_request_and_snapshot(self):
        from unittest import mock

        self.client.login(username="l@example.com", password="x")
        self.client.post(reverse("jobs:sync", args=[self.job.public_id]))
        r = self.client.post(f"/api/compute/jobs/{self.job.public_id}/progress", data='{"phase":"running"}', content_type="application/json", **self.auth)
        self.assertEqual(r.json()["action"], "sync")
        r = self.client.post(f"/api/compute/jobs/{self.job.public_id}/progress", data='{"phase":"running","synced":true}', content_type="application/json", **self.auth)
        self.assertEqual(r.json()["action"], "continue")
        self._post("m_hrr.csv", b"s,kW\nTime,HRR\n0,0\n")
        with mock.patch("apps.jobs.archives.build_archives_task.delay") as d:
            self.client.post(reverse("jobs:snapshot", args=[self.job.public_id]))
        d.assert_called_once_with(self.job.id)
        page = self.client.get(reverse("jobs:detail", args=[self.job.public_id]))
        self.assertContains(page, "Pobieranie w trakcie obliczeń")
        self.assertContains(page, "Pakuję")


class PurgeTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(JOB_DATA_ROOT=self.tmp)
        self.override.enable()
        self.user = get_user_model().objects.create_user(email="d2@example.com", password="x", kind="company")
        self.client.login(username="d2@example.com", password="x")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job(self, status):
        j = Job(owner=self.user, name="m", filename="m.fds", chid="m", status=status)
        j.save()
        j.results_dir.mkdir(parents=True)
        (j.results_dir / "m.out").write_text("x" * 1000)
        return j

    def test_user_delete_and_command(self):
        from io import StringIO

        from django.core.management import call_command

        done, running = self._job(Job.Status.DONE), self._job(Job.Status.RUNNING)
        self.client.post(reverse("jobs:delete", args=[running.public_id]))
        self.assertTrue(Job.objects.filter(pk=running.pk).exists())
        self.client.post(reverse("jobs:delete", args=[done.public_id]))
        done.refresh_from_db()
        self.assertIsNotNone(done.hidden_at)  # client delete: files gone, row kept for billing
        self.assertFalse(done.dir.exists())
        other = self._job(Job.Status.FAILED)
        out = StringIO()
        call_command("purge_jobs", "--all-finished", stdout=out)
        self.assertIn("dry run", out.getvalue())
        self.assertTrue(Job.objects.filter(pk=other.pk).exists())
        call_command("purge_jobs", "--all-finished", "--yes", stdout=out)
        self.assertFalse(Job.objects.filter(pk=other.pk).exists())
        self.assertTrue(Job.objects.filter(pk=running.pk).exists())


class HideTests(TestCase):
    def test_client_delete_hides_and_keeps_row(self):
        from django.contrib.auth import get_user_model

        from apps.compute.models import Machine

        tmp = tempfile.mkdtemp()
        with override_settings(JOB_DATA_ROOT=tmp):
            u = get_user_model().objects.create_user(email="h@example.com", password="x", kind="company")
            self.client.login(username="h@example.com", password="x")
            j = Job(owner=u, name="m", filename="m.fds", chid="m", status=Job.Status.DONE, price_pln=120)
            j.save()
            j.results_dir.mkdir(parents=True)
            (j.results_dir / "m.out").write_text("x")
            Machine.objects.create(job=j, name="x", server_type="cpx42", location="nbg1", status=Machine.Status.DELETED)
            self.client.post(reverse("jobs:delete", args=[j.public_id]))
            j.refresh_from_db()
            self.assertIsNotNone(j.hidden_at)
            self.assertFalse(j.dir.exists())
            self.assertEqual(self.client.get(reverse("jobs:detail", args=[j.public_id])).status_code, 404)
            self.assertNotContains(self.client.get(reverse("jobs:list")), j.public_id)
            from apps.jobs.purge import purge_job

            purge_job(j)
            m = Machine.objects.get(name="x")
            self.assertIsNone(m.job)
            self.assertIn("h@example.com", m.job_ref)
        shutil.rmtree(tmp, ignore_errors=True)


class StudentTests(TestCase):
    def test_domain_verification_and_rate(self):
        from apps.jobs.analyzer import multiplier_for

        a = User(email="jan@student.pw.edu.pl", kind="student")
        b = User(email="jan@gmail.com", kind="student")
        c = User(email="anna@tu-berlin.de", kind="student")
        self.assertTrue(a.check_student_domain())
        self.assertFalse(b.check_student_domain())
        self.assertTrue(c.check_student_domain())  # TU Berlin matches .tu-*.de
        self.assertFalse(User(email="x@firma.pl", kind="student").check_student_domain())  # admin decides
        self.assertEqual(multiplier_for(a), 3.0)
        self.assertEqual(multiplier_for(b), 6.0)
