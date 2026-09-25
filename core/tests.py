from django.test import SimpleTestCase
from django.urls import reverse


class HomePageTests(SimpleTestCase):
    """Check that visitors can access the BimmerHub homepage."""

    def test_homepage_loads_for_anonymous_visitors(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_home_url_resolves_to_root(self):
        self.assertEqual(reverse("core:home"), "/")

    def test_homepage_uses_expected_template(self):
        response = self.client.get("/")

        self.assertTemplateUsed(response, "core/home.html")

    def test_homepage_displays_site_name(self):
        response = self.client.get("/")

        self.assertContains(response, "BimmerHub")
