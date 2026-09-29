from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from parts.models import Category, Part


class BasketTests(TestCase):
    """Check quantities, server-side prices and basket protection."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Filters")
        cls.part = Part.objects.create(
            category=category,
            name="Test Oil Filter",
            description="A test filter.",
            part_number="BASKET-001",
            compatible_model="BMW F10",
            price=Decimal("24.99"),
            stock=5,
        )

    def setUp(self):
        self.basket_url = reverse("payments:basket_detail")
        self.add_url = reverse(
            "payments:basket_add", args=[self.part.pk]
        )
        self.update_url = reverse(
            "payments:basket_update", args=[self.part.pk]
        )
        self.remove_url = reverse(
            "payments:basket_remove", args=[self.part.pk]
        )
        self.key = str(self.part.pk)

    def test_empty_basket_is_public(self):
        response = self.client.get(self.basket_url)

        self.assertContains(response, "Your basket is empty.")

    def test_add_uses_database_price(self):
        response = self.client.post(
            self.add_url,
            {"quantity": 2, "price": "0.01"},
        )

        self.assertRedirects(response, self.basket_url)
        self.assertEqual(self.client.session["basket"][self.key], 2)

        response = self.client.get(self.basket_url)

        self.assertEqual(response.context["total"], Decimal("49.98"))

    def test_repeated_add_cannot_exceed_stock(self):
        self.client.post(self.add_url, {"quantity": 3})
        self.client.post(self.add_url, {"quantity": 3})

        self.assertEqual(self.client.session["basket"][self.key], 3)

    def test_invalid_quantities_are_rejected(self):
        for quantity in ("", "abc", "1.5", "0", "-1", "1000", "6"):
            with self.subTest(quantity=quantity):
                self.client.post(self.add_url, {"quantity": quantity})

                self.assertNotIn(
                    self.key,
                    self.client.session.get("basket", {}),
                )

    def test_out_of_stock_part_cannot_be_added(self):
        self.part.stock = 0
        self.part.save(update_fields=["stock"])

        self.client.post(self.add_url, {"quantity": 1})

        self.assertNotIn(self.key, self.client.session.get("basket", {}))

    def test_update_and_remove(self):
        self.client.post(self.add_url, {"quantity": 1})
        response = self.client.post(self.update_url, {"quantity": 4})

        self.assertRedirects(response, self.basket_url)
        self.assertEqual(self.client.session["basket"][self.key], 4)

        response = self.client.post(self.remove_url)

        self.assertRedirects(response, self.basket_url)
        self.assertNotIn(self.key, self.client.session["basket"])

    def test_invalid_update_keeps_previous_quantity(self):
        self.client.post(self.add_url, {"quantity": 2})

        for quantity in ("0", "invalid", "6"):
            with self.subTest(quantity=quantity):
                self.client.post(self.update_url, {"quantity": quantity})

                self.assertEqual(self.client.session["basket"][self.key], 2)

    def test_get_requests_cannot_change_basket(self):
        self.client.post(self.add_url, {"quantity": 2})

        for url in (self.add_url, self.update_url, self.remove_url):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 405)

        self.assertEqual(self.client.session["basket"][self.key], 2)

    def test_mutations_require_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)

        for url in (self.add_url, self.update_url, self.remove_url):
            with self.subTest(url=url):
                response = csrf_client.post(url, {"quantity": 1})

                self.assertEqual(response.status_code, 403)

    def test_baskets_are_separate_between_visitors(self):
        self.client.post(self.add_url, {"quantity": 2})
        other_client = Client()

        response = other_client.get(self.basket_url)

        self.assertContains(response, "Your basket is empty.")

    def test_current_price_and_stock_are_used(self):
        self.client.post(self.add_url, {"quantity": 2})

        self.part.price = Decimal("30.00")
        self.part.stock = 1
        self.part.save(update_fields=["price", "stock"])

        response = self.client.get(self.basket_url)

        self.assertEqual(response.context["total"], Decimal("60.00"))
        self.assertContains(
            response,
            "Your selected quantity is no longer available.",
        )

    def test_deleted_product_does_not_break_basket(self):
        self.client.post(self.add_url, {"quantity": 1})
        self.part.delete()

        response = self.client.get(self.basket_url)

        self.assertContains(response, "Your basket is empty.")
        self.assertEqual(response.context["total"], Decimal("0.00"))