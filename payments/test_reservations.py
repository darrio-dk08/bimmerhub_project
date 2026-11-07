from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from parts.models import Category, Part

from .models import Order, OrderItem
from .reservations import reserve_pending_order
from .services import CheckoutError


@override_settings(DELIVERY_CHARGE="30.00")
class StockReservationTests(TestCase):
    """Check stock reservation and repeated checkout attempts."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="reservation_customer",
        )
        cls.other_user = get_user_model().objects.create_user(
            username="other_reservation_customer",
        )

        category = Category.objects.create(name="Filters")
        cls.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter.",
            part_number="RESERVATION-FILTER-001",
            compatible_model="BMW F10 518d",
            price=Decimal("24.99"),
            stock=5,
        )

    def setUp(self):
        self.token = uuid4()
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

    def reserve(self, **overrides):
        arguments = {
            "user": self.user,
            "basket": self.basket,
            "delivery_data": self.delivery_data,
            "checkout_token": self.token,
        }
        arguments.update(overrides)
        return reserve_pending_order(**arguments)

    def test_reserves_stock_and_leaves_order_unpaid(self):
        order = self.reserve()

        self.part.refresh_from_db()

        self.assertEqual(self.part.stock, 3)
        self.assertTrue(order.stock_reserved)
        self.assertEqual(order.checkout_token, self.token)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertIsNone(order.paid_at)
        self.assertEqual(order.total, Decimal("79.98"))
        self.assertEqual(self.basket, {str(self.part.pk): 2})

    def test_identical_retry_returns_same_order_without_reserving_again(self):
        first_order = self.reserve()
        second_order = self.reserve()

        self.part.refresh_from_db()

        self.assertEqual(first_order.pk, second_order.pk)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)
        self.assertEqual(self.part.stock, 3)

    def test_retry_works_after_reserving_all_remaining_stock(self):
        basket = {str(self.part.pk): 5}

        first_order = self.reserve(basket=basket)
        second_order = self.reserve(basket=basket)

        self.part.refresh_from_db()

        self.assertEqual(first_order.pk, second_order.pk)
        self.assertEqual(self.part.stock, 0)
        self.assertEqual(Order.objects.count(), 1)

    def test_another_user_cannot_reuse_checkout_token(self):
        original = self.reserve()

        with self.assertRaises(CheckoutError):
            self.reserve(user=self.other_user)

        self.part.refresh_from_db()

        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(original.user, self.user)
        self.assertEqual(self.part.stock, 3)

    def test_changed_basket_or_address_cannot_reuse_token(self):
        self.reserve()

        changed_requests = [
            {"basket": {str(self.part.pk): 1}},
            {
                "delivery_data": {
                    **self.delivery_data,
                    "address_line1": "99 Different Street",
                },
            },
        ]

        for changes in changed_requests:
            with self.subTest(changes=changes):
                with self.assertRaises(CheckoutError):
                    self.reserve(**changes)

        self.part.refresh_from_db()

        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.part.stock, 3)

    def test_second_customer_cannot_reserve_unavailable_stock(self):
        self.reserve(basket={str(self.part.pk): 4})

        with self.assertRaises(CheckoutError):
            self.reserve(
                user=self.other_user,
                checkout_token=uuid4(),
                basket={str(self.part.pk): 2},
            )

        self.part.refresh_from_db()

        self.assertEqual(self.part.stock, 1)
        self.assertEqual(Order.objects.count(), 1)

    def test_failure_after_stock_deduction_rolls_everything_back(self):
        real_save = Order.save

        def fail_reserved_save(instance, *args, **kwargs):
            if instance.stock_reserved:
                raise RuntimeError("Simulated reservation save failure.")
            return real_save(instance, *args, **kwargs)

        with patch.object(Order, "save", new=fail_reserved_save):
            with self.assertRaises(RuntimeError):
                self.reserve()

        self.part.refresh_from_db()

        self.assertEqual(self.part.stock, 5)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)

    def test_invalid_checkout_token_is_rejected(self):
        with self.assertRaises(CheckoutError):
            self.reserve(checkout_token="not-a-uuid")

        self.part.refresh_from_db()

        self.assertEqual(self.part.stock, 5)
        self.assertEqual(Order.objects.count(), 0)