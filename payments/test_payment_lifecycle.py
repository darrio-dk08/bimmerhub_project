from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import stripe

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from parts.models import Category, Part

from .models import Order
from .payment_lifecycle import release_expired_reservation
from .reservations import reserve_pending_order
from .services import CheckoutError


@override_settings(
    DELIVERY_CHARGE="30.00",
    STRIPE_SECRET_KEY="sk_test_fake_key_for_unit_tests",
)
class ReservationReleaseTests(TestCase):
    """Check verified expiry, repeat processing and release rollback."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="release_customer",
        )
        category = Category.objects.create(name="Filters")

        cls.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter.",
            part_number="RELEASE-FILTER-001",
            compatible_model="BMW F10 518d",
            price=Decimal("24.99"),
            stock=5,
        )

    def setUp(self):
        self.order = reserve_pending_order(
            user=self.user,
            basket={str(self.part.pk): 2},
            delivery_data={
                "full_name": "Test Customer",
                "email": "customer@example.com",
                "phone": "0871234567",
                "address_line1": "1 Test Street",
                "address_line2": "",
                "town_or_city": "Donegal",
                "county": "",
                "postal_code": "",
                "country": "IE",
            },
            checkout_token=uuid4(),
        )
        self.order.stripe_checkout_session_id = "cs_test_release"
        self.order.save(
            update_fields=["stripe_checkout_session_id"],
        )

        self.session = {
            "id": "cs_test_release",
            "client_reference_id": str(self.order.reference),
            "livemode": False,
            "mode": "payment",
            "currency": "eur",
            "amount_total": 7998,
            "status": "expired",
            "payment_status": "unpaid",
        }

        patcher = patch(
            "payments.payment_lifecycle.stripe.StripeClient"
        )
        self.mock_client_class = patcher.start()
        self.addCleanup(patcher.stop)

        self.retrieve = (
            self.mock_client_class.return_value
            .v1.checkout.sessions.retrieve
        )
        self.retrieve.return_value = self.session

    def release(self):
        return release_expired_reservation(
            order_id=self.order.pk,
        )

    def assert_reservation_unchanged(self):
        self.part.refresh_from_db()
        self.order.refresh_from_db()

        self.assertEqual(self.part.stock, 3)
        self.assertTrue(self.order.stock_reserved)
        self.assertEqual(self.order.status, Order.Status.PENDING)

    def test_expired_unpaid_session_restores_stock_only_once(self):
        self.assertTrue(self.release())
        self.assertFalse(self.release())

        self.part.refresh_from_db()
        self.order.refresh_from_db()

        self.assertEqual(self.part.stock, 5)
        self.assertFalse(self.order.stock_reserved)
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertIsNone(self.order.paid_at)
        self.assertEqual(self.order.items.count(), 1)
        self.retrieve.assert_called_once_with("cs_test_release")

    def test_paid_order_never_releases_stock(self):
        self.order.status = Order.Status.PAID
        self.order.paid_at = timezone.now()
        self.order.save(update_fields=["status", "paid_at"])

        self.assertFalse(self.release())

        self.part.refresh_from_db()
        self.order.refresh_from_db()

        self.assertEqual(self.part.stock, 3)
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.retrieve.assert_not_called()

    def test_open_complete_or_paid_sessions_do_not_release_stock(self):
        states = [
            ("open", "unpaid"),
            ("complete", "paid"),
            ("complete", "unpaid"),
            ("expired", "paid"),
        ]

        for status, payment_status in states:
            with self.subTest(
                status=status,
                payment_status=payment_status,
            ):
                self.retrieve.return_value = {
                    **self.session,
                    "status": status,
                    "payment_status": payment_status,
                }

                self.assertFalse(self.release())
                self.assert_reservation_unchanged()

    def test_mismatched_session_is_rejected(self):
        invalid_values = [
            {"id": "cs_test_another_session"},
            {"client_reference_id": str(uuid4())},
            {"livemode": True},
            {"mode": "subscription"},
            {"currency": "usd"},
            {"amount_total": 1},
        ]

        for values in invalid_values:
            with self.subTest(values=values):
                self.retrieve.return_value = {
                    **self.session,
                    **values,
                }

                with self.assertRaises(CheckoutError):
                    self.release()

                self.assert_reservation_unchanged()

    def test_stripe_error_keeps_stock_reserved(self):
        self.retrieve.side_effect = stripe.APIConnectionError(
            "Simulated connection failure."
        )

        with self.assertRaises(CheckoutError):
            self.release()

        self.assert_reservation_unchanged()

    def test_missing_stripe_session_does_not_release_stock(self):
        self.order.stripe_checkout_session_id = None
        self.order.save(
            update_fields=["stripe_checkout_session_id"],
        )

        with self.assertRaises(CheckoutError):
            self.release()

        self.assert_reservation_unchanged()
        self.retrieve.assert_not_called()

    def test_database_failure_rolls_back_stock_release(self):
        with patch.object(
            Order,
            "save",
            side_effect=RuntimeError("Simulated save failure."),
        ):
            with self.assertRaises(RuntimeError):
                self.release()

        self.assert_reservation_unchanged()

    def test_payment_recorded_during_api_call_prevents_release(self):
        def retrieve_after_payment(session_id):
            Order.objects.filter(pk=self.order.pk).update(
                status=Order.Status.PAID,
                paid_at=timezone.now(),
            )
            return self.session

        self.retrieve.side_effect = retrieve_after_payment

        self.assertFalse(self.release())

        self.part.refresh_from_db()
        self.order.refresh_from_db()

        self.assertEqual(self.part.stock, 3)
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.paid_at)
