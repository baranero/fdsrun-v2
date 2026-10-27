import importlib.util
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

AGENT = Path(settings.BASE_DIR).parent / "compute" / "agent.py"
spec = importlib.util.spec_from_file_location("agent", AGENT)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

VERBOSE = """       Time Step      868   October 26, 2026  21:41:38
       Step Size:  0.215E-02 s, Total Time:   10.00000 s
       Pressure Iterations: 7
"""
COMPACT = """ Time Step:  219900, Simulation Time: 999.79973 s, Step Size: 0.373E-02 s, Pressure Iterations: 3
 Time Step:  219954, Simulation Time: 1000.0000 s, Step Size: 0.281E-02 s, Pressure Iterations: 4
"""


class AgentParserTests(SimpleTestCase):
    def test_verbose_format(self):
        self.assertEqual(agent.parse_last_step(VERBOSE), {"step": 868, "t": 10.0, "dt": 0.00215})

    def test_compact_format(self):
        self.assertEqual(agent.parse_last_step(COMPACT), {"step": 219954, "t": 1000.0, "dt": 0.00281})

    def test_nothing(self):
        self.assertIsNone(agent.parse_last_step("FDS starting\n"))


from django.test import TestCase as _TestCase  # noqa: E402


class JobRetryTests(_TestCase):
    def test_retry_creates_queued_copy(self):
        from io import StringIO
        from pathlib import Path
        from unittest import mock

        from django.contrib.auth import get_user_model
        from django.core.management import call_command

        from apps.jobs.models import Job

        user = get_user_model().objects.create_user(email="r@example.com", password="x", kind="company")
        fixture = Path(__file__).parent.parent / "jobs" / "fixtures" / "minimal.fds"
        orig = Job(owner=user, name="m", filename="minimal.fds", status=Job.Status.FAILED, procs=1, server_type="cpx32")
        orig.save()
        orig.input_path.parent.mkdir(parents=True, exist_ok=True)
        orig.input_path.write_text(fixture.read_text())
        out = StringIO()
        with mock.patch("apps.compute.tasks.launch_job.delay") as launch:
            call_command("job_retry", orig.public_id, stdout=out)
        new = Job.objects.exclude(pk=orig.pk).get(owner=user)
        self.assertEqual(new.status, Job.Status.QUEUED)
        self.assertTrue(new.run_path.exists())
        launch.assert_called_once_with(new.id)
        self.assertIn(new.public_id, out.getvalue())
