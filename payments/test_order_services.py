from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings

from parts.models import Category, Part

from .models import Order, OrderItem
from .services import CheckoutError, create_pending_order


@override_settings(DELIVERY_CHARGE="30.00")
class OrderCreationTests(TestCase):
    """Check pending-order validation, prices and atomic saving."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="service_customer",
        )
        cls.other_user = get_user_model().objects.create_user(
            username="other_customer",
        )
        category = Category.objects.create(name="Filters")

        cls.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter.",
            part_number="SERVICE-FILTER-001",
            compatible_model="BMW F10 518d",
            price=Decimal("24.99"),
            stock=5,
        )

    def setUp(self):
        self.basket = {str(self.part.pk): 2}
        self.delivery_data = {
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

    def create_order(self, **overrides):
        arguments = {
            "user": self.user,
            "basket": self.basket,
            "delivery_data": self.delivery_data,
        }
        arguments.update(overrides)
        return create_pending_order(**arguments)

    def assert_no_order_records(self):
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)

    def test_creates_unpaid_order_with_server_values_and_snapshots(self):
        submitted_data = {
            **self.delivery_data,
            "user": str(self.other_user.pk),
            "total": "0.01",
            "delivery_cost": "0.00",
            "currency": "usd",
            "status": "paid",
        }

        order = self.create_order(delivery_data=submitted_data)
        item = order.items.get()

        self.assertEqual(order.user, self.user)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertIsNone(order.paid_at)
        self.assertIsNone(order.stripe_checkout_session_id)
        self.assertIsNone(order.stripe_payment_intent_id)
        self.assertEqual(order.currency, "eur")
        self.assertEqual(order.country, "IE")
        self.assertEqual(order.delivery_cost, Decimal("30.00"))
        self.assertEqual(order.total, Decimal("79.98"))
        self.assertEqual(order.items_subtotal, Decimal("49.98"))

        self.assertEqual(item.part, self.part)
        self.assertEqual(item.product_name, self.part.name)
        self.assertEqual(item.part_number, self.part.part_number)
        self.assertEqual(item.unit_price, Decimal("24.99"))
        self.assertEqual(item.quantity, 2)

        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 5)
        self.assertEqual(self.basket, {str(self.part.pk): 2})

    def test_anonymous_user_cannot_create_order(self):
        with self.assertRaises(CheckoutError):
            self.create_order(user=AnonymousUser())

        self.assert_no_order_records()

    def test_empty_or_malformed_basket_is_rejected(self):
        invalid_baskets = [
            {},
            [],
            {"invalid": 1},
            {"0": 1},
            {"01": 1},
            {"999999999999999999999999": 1},
        ]

        for basket in invalid_baskets:
            with self.subTest(basket=basket):
                with self.assertRaises(CheckoutError):
                    self.create_order(basket=basket)

                self.assert_no_order_records()

    def test_invalid_quantities_are_rejected(self):
        for quantity in (0, -1, 1000, "2", 1.5, True):
            with self.subTest(quantity=quantity):
                with self.assertRaises(CheckoutError):
                    self.create_order(
                        basket={str(self.part.pk): quantity},
                    )

                self.assert_no_order_records()

    def test_invalid_delivery_details_are_rejected(self):
        invalid_values = [
            {"country": "GB"},
            {"email": "not-an-email"},
            {"address_line1": ""},
        ]

        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(CheckoutError):
                    self.create_order(
                        delivery_data={
                            **self.delivery_data,
                            **values,
                        },
                    )

                self.assert_no_order_records()

    def test_deleted_product_prevents_order_creation(self):
        deleted_key = str(self.part.pk)
        self.part.delete()

        with self.assertRaises(CheckoutError):
            self.create_order(basket={deleted_key: 2})

        self.assert_no_order_records()

    def test_insufficient_stock_prevents_order_creation(self):
        self.part.stock = 1
        self.part.save(update_fields=["stock"])

        with self.assertRaises(CheckoutError):
            self.create_order()

        self.assert_no_order_records()
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 1)

    def test_current_price_is_used_and_saved_snapshot_is_preserved(self):
        self.part.price = Decimal("30.00")
        self.part.save(update_fields=["price"])

        order = self.create_order()

        self.assertEqual(order.total, Decimal("90.00"))
        self.assertEqual(
            order.items.get().unit_price,
            Decimal("30.00"),
        )

        self.part.price = Decimal("40.00")
        self.part.name = "Updated catalogue name"
        self.part.save(update_fields=["price", "name"])

        order.refresh_from_db()
        item = order.items.get()

        self.assertEqual(order.total, Decimal("90.00"))
        self.assertEqual(item.unit_price, Decimal("30.00"))
        self.assertEqual(item.product_name, "BMW F10 Oil Filter")

    def test_item_save_failure_rolls_back_order_and_previous_items(self):
        second_part = Part.objects.create(
            category=self.part.category,
            name="Another filter",
            description="Second test product.",
            part_number="SERVICE-FILTER-002",
            compatible_model="BMW F30",
            price=Decimal("10.00"),
            stock=5,
        )
        basket = {
            str(self.part.pk): 2,
            str(second_part.pk): 1,
        }

        real_save = OrderItem.save

        def fail_second_item(instance, *args, **kwargs):
            if instance.part_id == second_part.pk:
                raise RuntimeError("Simulated item save failure.")
            return real_save(instance, *args, **kwargs)

        with patch.object(OrderItem, "save", new=fail_second_item):
            with self.assertRaises(RuntimeError):
                self.create_order(basket=basket)

        self.assert_no_order_records()
