from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User


class PanelTests(TestCase):
    def test_only_staff(self):
        User.objects.create_user("zwykly@example.com", "haslo-bardzo-tajne")
        self.client.login(username="zwykly@example.com", password="haslo-bardzo-tajne")
        self.assertEqual(self.client.get(reverse("panel:dashboard")).status_code, 302)

    def test_pages_render(self):
        User.objects.create_superuser("szef@example.com", "haslo-bardzo-tajne")
        self.client.login(username="szef@example.com", password="haslo-bardzo-tajne")
        for name in ("dashboard", "jobs", "users", "machines", "access"):
            self.assertEqual(self.client.get(reverse(f"panel:{name}")).status_code, 200, name)
