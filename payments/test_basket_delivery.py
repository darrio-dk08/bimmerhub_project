from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from parts.models import Category, Part

from .basket import BASKET_SESSION_KEY


@override_settings(DELIVERY_CHARGE="30.00")
class BasketDeliveryTests(TestCase):
    """Check delivery is charged once and only for a populated basket."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Filters")
        cls.part = Part.objects.create(
            category=category,
            name="Test oil filter",
            description="Filter for delivery tests.",
            part_number="DELIVERY-FILTER-001",
            compatible_model="BMW F10",
            price=Decimal("24.99"),
            stock=5,
        )

    def test_empty_basket_has_no_delivery_charge(self):
        response = self.client.get(reverse("payments:basket_detail"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], Decimal("0.00"))
        self.assertEqual(
            response.context["delivery_cost"],
            Decimal("0.00"),
        )
        self.assertEqual(
            response.context["grand_total"],
            Decimal("0.00"),
        )

    def test_delivery_is_charged_once_for_multiple_units(self):
        session = self.client.session
        session[BASKET_SESSION_KEY] = {str(self.part.pk): 2}
        session.save()

        response = self.client.get(reverse("payments:basket_detail"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], Decimal("49.98"))
        self.assertEqual(
            response.context["delivery_cost"],
            Decimal("30.00"),
        )
        self.assertEqual(
            response.context["grand_total"],
            Decimal("79.98"),
        )
        self.assertContains(response, "Delivery within Ireland:")
        self.assertContains(response, "79.98")