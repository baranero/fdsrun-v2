from django.test import SimpleTestCase
from django.urls import reverse


class LegalPagesTests(SimpleTestCase):
    def test_pages(self):
        for name in ("terms", "privacy", "cookies", "dpa"):
            r = self.client.get(reverse(f"legal:{name}"))
            self.assertEqual(r.status_code, 200, name)
            self.assertContains(r, "fp-solutions")
