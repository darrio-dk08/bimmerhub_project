from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Vehicle


class GarageTests(TestCase):
    """Check vehicle management and ownership protection."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(username="owner")
        cls.other_user = User.objects.create_user(username="other")

        cls.vehicle = Vehicle.objects.create(
            user=cls.owner,
            make="BMW",
            model="F10 518d",
            year=2013,
            engine="2.0 diesel",
            registration="OWNER-001",
        )
        cls.other_vehicle = Vehicle.objects.create(
            user=cls.other_user,
            make="BMW",
            model="F30 320d",
            year=2015,
            engine="2.0 diesel",
            registration="OTHER-002",
        )

    def setUp(self):
        self.client.force_login(self.owner)
        self.list_url = reverse("garage:vehicle_list")
        self.add_url = reverse("garage:vehicle_create")
        self.edit_url = reverse(
            "garage:vehicle_update",
            args=[self.vehicle.pk],
        )
        self.delete_url = reverse(
            "garage:vehicle_delete",
            args=[self.vehicle.pk],
        )
        self.valid_data = {
            "make": "BMW",
            "model": "G30 520d",
            "year": 2020,
            "engine": "2.0 diesel",
            "registration": "",
        }

    def test_anonymous_visitors_must_log_in(self):
        self.client.logout()

        for url in (
            self.list_url,
            self.add_url,
            self.edit_url,
            self.delete_url,
        ):
            for method in ("get", "post"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url)

                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(
                        response.url.startswith(reverse("account_login"))
                    )

        self.assertEqual(Vehicle.objects.count(), 2)

    def test_list_shows_only_owned_vehicles(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["vehicles"]),
            [self.vehicle],
        )
        self.assertNotContains(response, self.other_vehicle.registration)

    def test_create_assigns_owner_and_ignores_submitted_user(self):
        data = {
            **self.valid_data,
            "user": self.other_user.pk,
        }
        response = self.client.post(self.add_url, data)

        self.assertRedirects(response, self.list_url)
        created = Vehicle.objects.get(model="G30 520d")
        self.assertEqual(created.user, self.owner)

    def test_owner_can_edit_vehicle(self):
        response = self.client.post(self.edit_url, self.valid_data)

        self.assertRedirects(response, self.list_url)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.model, "G30 520d")
        self.assertEqual(self.vehicle.user, self.owner)

    def test_invalid_year_does_not_create_or_update(self):
        data = {**self.valid_data, "year": 0}

        for url in (self.add_url, self.edit_url):
            with self.subTest(url=url):
                response = self.client.post(url, data)

                self.assertEqual(response.status_code, 200)
                self.assertIn("year", response.context["form"].errors)

        self.assertEqual(Vehicle.objects.count(), 2)
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.year, 2013)

    def test_other_user_cannot_edit_or_delete_vehicle(self):
        self.client.force_login(self.other_user)

        for url in (self.edit_url, self.delete_url):
            for method in ("get", "post"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(
                        url,
                        self.valid_data,
                    )
                    self.assertEqual(response.status_code, 404)

        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.model, "F10 518d")
        self.assertEqual(self.vehicle.user, self.owner)

    def test_delete_requires_confirmation_post(self):
        response = self.client.get(self.delete_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "garage/vehicle_confirm_delete.html",
        )
        self.assertTrue(
            Vehicle.objects.filter(pk=self.vehicle.pk).exists()
        )

        response = self.client.post(self.delete_url)

        self.assertRedirects(response, self.list_url)
        self.assertFalse(
            Vehicle.objects.filter(pk=self.vehicle.pk).exists()
        )

    def test_delete_without_csrf_token_is_rejected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)

        response = csrf_client.post(self.delete_url)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            Vehicle.objects.filter(pk=self.vehicle.pk).exists()
        )