from decimal import Decimal
from unittest.mock import patch

import stripe

from django.test import TestCase, override_settings

from parts.models import Category, Part

from .checkout_recovery import recover_checkout_session
from .models import Order, OrderItem
from .services import CheckoutError
from .stripe_checkout import _build_request


@override_settings(
    STRIPE_SECRET_KEY="sk_test_fake_key_for_unit_tests",
    STRIPE_RETURN_BASE_URL="http://127.0.0.1:8000",
)
class CheckoutRecoveryTests(TestCase):
    """Check recovery after a Stripe session ID was not saved."""

    def setUp(self):
        category = Category.objects.create(name="Filters")

        # Five original units, with two already reserved.
        self.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter.",
            part_number="RECOVERY-FILTER-001",
            compatible_model="BMW F10 518d",
            price=Decimal("24.99"),
            stock=3,
        )

        self.order = Order.objects.create(
            full_name="Test Customer",
            email="customer@example.com",
            phone="0871234567",
            address_line1="1 Test Street",
            town_or_city="Donegal",
            country="IE",
            delivery_cost=Decimal("30.00"),
            total=Decimal("79.98"),
            stock_reserved=True,
        )

        OrderItem.objects.create(
            order=self.order,
            part=self.part,
            product_name=self.part.name,
            part_number=self.part.part_number,
            unit_price=Decimal("24.99"),
            quantity=2,
        )

        self.order.stripe_checkout_request = _build_request(self.order)
        self.order.save(update_fields=["stripe_checkout_request"])

        self.session = {
            "id": "cs_test_recovery",
            "livemode": False,
            "mode": "payment",
            "client_reference_id": str(self.order.reference),
            "metadata": {
                "order_reference": str(self.order.reference),
            },
            "currency": "eur",
            "amount_total": 7998,
            "status": "open",
            "payment_status": "unpaid",
            "payment_intent": None,
            "expires_at": self.order.stripe_checkout_request["expires_at"],
        }

        # All three services use the same imported stripe module.
        # This patch prevents real Stripe requests throughout recovery.
        patcher = patch(
            "payments.checkout_recovery.stripe.StripeClient"
        )
        mock_client = patcher.start()
        self.addCleanup(patcher.stop)

        sessions = mock_client.return_value.v1.checkout.sessions
        self.retrieve_session = sessions.retrieve
        self.create_session = sessions.create
        self.retrieve_session.return_value = self.session

    def recover(self):
        return recover_checkout_session(
            session_id="cs_test_recovery",
        )

    def assert_reservation_unchanged(self):
        self.order.refresh_from_db()
        self.part.refresh_from_db()

        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.assertIsNone(self.order.paid_at)
        self.assertTrue(self.order.stock_reserved)
        self.assertEqual(self.part.stock, 3)

    def test_open_session_is_linked_without_creating_another_session(self):
        recovered = self.recover()

        self.assertEqual(recovered.pk, self.order.pk)
        self.assertEqual(
            recovered.stripe_checkout_session_id,
            "cs_test_recovery",
        )
        self.assert_reservation_unchanged()
        self.create_session.assert_not_called()

    def test_paid_session_is_recovered_and_payment_recorded_once(self):
        self.session.update(
            status="complete",
            payment_status="paid",
            payment_intent="pi_test_recovery",
        )

        first = self.recover()
        second = self.recover()
        self.part.refresh_from_db()

        self.assertEqual(first.status, Order.Status.PAID)
        self.assertIsNotNone(first.paid_at)
        self.assertEqual(first.paid_at, second.paid_at)
        self.assertEqual(
            second.stripe_payment_intent_id,
            "pi_test_recovery",
        )
        self.assertEqual(self.part.stock, 3)
        self.create_session.assert_not_called()

    def test_expired_session_restores_stock_only_once(self):
        self.session.update(
            status="expired",
            payment_status="unpaid",
        )

        self.recover()
        recovered = self.recover()
        self.part.refresh_from_db()

        self.assertEqual(recovered.status, Order.Status.CANCELLED)
        self.assertFalse(recovered.stock_reserved)
        self.assertIsNone(recovered.paid_at)
        self.assertEqual(self.part.stock, 5)
        self.create_session.assert_not_called()

    def test_different_existing_session_is_not_overwritten(self):
        self.order.stripe_checkout_session_id = "cs_test_existing"
        self.order.save(update_fields=["stripe_checkout_session_id"])

        with self.assertRaises(CheckoutError):
            self.recover()

        self.assert_reservation_unchanged()
        self.assertEqual(
            self.order.stripe_checkout_session_id,
            "cs_test_existing",
        )

    def test_mismatched_stripe_details_do_not_link_session(self):
        changes = [
            {"id": "cs_test_other"},
            {"client_reference_id": "invalid-reference"},
            {"metadata": {"order_reference": "another-order"}},
            {"livemode": True},
            {"currency": "usd"},
            {"amount_total": 1},
            {"expires_at": self.session["expires_at"] + 60},
        ]

        for values in changes:
            with self.subTest(values=values):
                self.retrieve_session.return_value = {
                    **self.session,
                    **values,
                }

                with self.assertRaises(CheckoutError):
                    self.recover()

                self.assert_reservation_unchanged()
                self.assertIsNone(
                    self.order.stripe_checkout_session_id,
                )

    def test_missing_saved_request_prevents_automatic_recovery(self):
        self.order.stripe_checkout_request = {}
        self.order.save(update_fields=["stripe_checkout_request"])

        with self.assertRaises(CheckoutError):
            self.recover()

        self.assert_reservation_unchanged()
        self.assertIsNone(self.order.stripe_checkout_session_id)

    def test_stripe_timeout_keeps_reservation_and_missing_session_id(self):
        self.retrieve_session.side_effect = stripe.APIConnectionError(
            "Simulated timeout."
        )

        with self.assertRaises(CheckoutError):
            self.recover()

        self.assert_reservation_unchanged()
        self.assertIsNone(self.order.stripe_checkout_session_id)

    def test_cancelled_order_cannot_attach_a_new_session(self):
        self.order.status = Order.Status.CANCELLED
        self.order.stock_reserved = False
        self.order.save(update_fields=["status", "stock_reserved"])

        with self.assertRaises(CheckoutError):
            self.recover()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertIsNone(self.order.stripe_checkout_session_id)

    def test_failed_link_save_can_be_retried(self):
        real_save = Order.save

        def save_then_fail(instance, *args, **kwargs):
            real_save(instance, *args, **kwargs)
            raise RuntimeError("Simulated database failure.")

        with patch.object(Order, "save", new=save_then_fail):
            with self.assertRaises(RuntimeError):
                self.recover()

        self.assert_reservation_unchanged()
        self.assertIsNone(self.order.stripe_checkout_session_id)

        recovered = self.recover()
        self.assertEqual(
            recovered.stripe_checkout_session_id,
            "cs_test_recovery",
        )

    def test_payment_verification_failure_keeps_recovered_session_id(self):
        paid_session = {
            **self.session,
            "status": "complete",
            "payment_status": "paid",
            "payment_intent": "pi_test_recovery",
        }
        self.retrieve_session.side_effect = [
            paid_session,
            stripe.APIConnectionError("Verification timeout."),
        ]

        with self.assertRaises(CheckoutError):
            self.recover()

        self.assert_reservation_unchanged()
        self.assertEqual(
            self.order.stripe_checkout_session_id,
            "cs_test_recovery",
        )

        # A later retry can finish payment verification.
        self.retrieve_session.side_effect = None
        self.retrieve_session.return_value = paid_session

        recovered = self.recover()
        self.assertEqual(recovered.status, Order.Status.PAID)