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
