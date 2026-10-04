from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from parts.models import Category, Part

from .models import Order, OrderItem


class OrderModelTests(TestCase):
    """Check order history, calculations and database protection."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="order_customer",
        )
        category = Category.objects.create(name="Filters")
        cls.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter.",
            part_number="ORDER-FILTER-001",
            compatible_model="BMW F10 518d",
            price=Decimal("24.99"),
            stock=5,
        )
        cls.order = Order.objects.create(
            user=cls.user,
            full_name="Test Customer",
            email="customer@example.com",
            phone="0871234567",
            address_line1="1 Test Street",
            town_or_city="Donegal",
            country="IE",
            total=Decimal("49.98"),
        )
        cls.item = OrderItem.objects.create(
            order=cls.order,
            part=cls.part,
            product_name=cls.part.name,
            part_number=cls.part.part_number,
            unit_price=cls.part.price,
            quantity=2,
        )

    def test_new_order_is_unpaid(self):
        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.assertIsNone(self.order.paid_at)
        self.assertEqual(self.order.currency, "eur")

    def test_item_subtotal_uses_decimal_price(self):
        self.assertEqual(self.item.subtotal, Decimal("49.98"))

    def test_catalogue_changes_preserve_order_history(self):
        self.part.name = "Updated filter"
        self.part.part_number = "UPDATED-FILTER-001"
        self.part.price = Decimal("30.00")
        self.part.save()

        self.item.refresh_from_db()
        self.order.refresh_from_db()

        self.assertEqual(self.item.product_name, "BMW F10 Oil Filter")
        self.assertEqual(self.item.part_number, "ORDER-FILTER-001")
        self.assertEqual(self.item.unit_price, Decimal("24.99"))
        self.assertEqual(self.item.subtotal, Decimal("49.98"))
        self.assertEqual(self.order.total, Decimal("49.98"))

    def test_deleting_product_preserves_order_item(self):
        self.part.delete()

        self.item.refresh_from_db()

        self.assertIsNone(self.item.part_id)
        self.assertEqual(self.item.product_name, "BMW F10 Oil Filter")
        self.assertEqual(self.item.subtotal, Decimal("49.98"))
        self.assertTrue(
            Order.objects.filter(pk=self.order.pk).exists()
        )

    def test_deleting_user_preserves_order(self):
        self.user.delete()

        self.order.refresh_from_db()

        self.assertIsNone(self.order.user_id)
        self.assertEqual(self.order.full_name, "Test Customer")
        self.assertEqual(self.order.items.count(), 1)

    def test_database_rejects_negative_order_total(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Order.objects.filter(pk=self.order.pk).update(
                    total=Decimal("-0.01"),
                )

        self.order.refresh_from_db()
        self.assertEqual(self.order.total, Decimal("49.98"))

    def test_database_rejects_invalid_item_values(self):
        invalid_values = [
            {"quantity": 0},
            {"quantity": -1},
            {"quantity": 1000},
            {"unit_price": Decimal("-0.01")},
        ]

        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        OrderItem.objects.filter(
                            pk=self.item.pk,
                        ).update(**values)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 2)
        self.assertEqual(self.item.unit_price, Decimal("24.99"))

    def test_order_total_includes_saved_delivery(self):
        self.order.delivery_cost = Decimal("30.00")
        self.order.total = Decimal("79.98")
        self.order.save()
        self.order.refresh_from_db()

        self.assertEqual(self.order.items_subtotal, Decimal("49.98"))
        self.assertEqual(self.order.delivery_cost, Decimal("30.00"))
        self.assertEqual(self.order.total, Decimal("79.98"))

    def test_database_rejects_invalid_delivery_cost(self):
        invalid_costs = [
            Decimal("-0.01"),
            Decimal("50.00"),
        ]

        # This test order has a total of 49.98.
        for cost in invalid_costs:
            with self.subTest(delivery_cost=cost):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        Order.objects.filter(pk=self.order.pk).update(
                            delivery_cost=cost,
                        )

        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_cost, Decimal("0.00"))