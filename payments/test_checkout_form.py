from django.test import TestCase

from .forms import CheckoutForm
from .models import Order


class CheckoutFormTests(TestCase):
    """Check checkout details and Ireland-only delivery."""

    def setUp(self):
        self.valid_data = {
            "full_name": "Test Customer",
            "email": "customer@example.com",
            "phone": "0871234567",
            "address_line1": "1 Test Street",
            "address_line2": "",
            "town_or_city": "Donegal",
            "county": "",
            "postal_code": "",
            "country": "IE",
        }

    def test_valid_irish_address_is_accepted(self):
        form = CheckoutForm(data=self.valid_data)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["country"], "IE")
        self.assertEqual(Order.objects.count(), 0)

    def test_required_fields_cannot_be_blank(self):
        required_fields = [
            "full_name",
            "email",
            "phone",
            "address_line1",
            "town_or_city",
            "country",
        ]

        for field in required_fields:
            with self.subTest(field=field):
                data = {**self.valid_data, field: ""}
                form = CheckoutForm(data=data)

                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_invalid_email_is_rejected(self):
        data = {**self.valid_data, "email": "not-an-email"}
        form = CheckoutForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_other_delivery_countries_are_rejected(self):
        for country in ("GB", "US", "FR", "invalid"):
            with self.subTest(country=country):
                data = {**self.valid_data, "country": country}
                form = CheckoutForm(data=data)

                self.assertFalse(form.is_valid())
                self.assertIn("country", form.errors)

    def test_customer_cannot_set_protected_order_fields(self):
        data = {
            **self.valid_data,
            "user": "999",
            "total": "0.01",
            "delivery_cost": "0.00",
            "status": "paid",
            "currency": "usd",
        }
        form = CheckoutForm(data=data)

        self.assertTrue(form.is_valid(), form.errors)

        for field in (
            "user",
            "total",
            "delivery_cost",
            "status",
            "currency",
        ):
            self.assertNotIn(field, form.fields)
            self.assertNotIn(field, form.cleaned_data)

        self.assertEqual(Order.objects.count(), 0)