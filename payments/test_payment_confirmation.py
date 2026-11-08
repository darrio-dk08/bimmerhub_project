from decimal import Decimal
from unittest.mock import patch

import stripe

from django.test import TestCase, override_settings

from parts.models import Category, Part

from .models import Order, OrderItem
from .payment_confirmation import confirm_order_payment
from .services import CheckoutError


@override_settings(
    STRIPE_SECRET_KEY="sk_test_fake_key_for_unit_tests",
)
class PaymentConfirmationTests(TestCase):
    """Check verified payment recording and repeat confirmations."""

    def setUp(self):
        category = Category.objects.create(name="Filters")

        # Represents five original units with two already reserved.
        self.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter.",
            part_number="CONFIRM-FILTER-001",
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
            stripe_checkout_session_id="cs_test_confirmation",
        )

        OrderItem.objects.create(
            order=self.order,
            part=self.part,
            product_name=self.part.name,
            part_number=self.part.part_number,
            unit_price=Decimal("24.99"),
            quantity=2,
        )

        self.session = {
            "id": "cs_test_confirmation",
            "livemode": False,
            "mode": "payment",
            "client_reference_id": str(self.order.reference),
            "currency": "eur",
            "amount_total": 7998,
            "status": "complete",
            "payment_status": "paid",
            "payment_intent": "pi_test_confirmation",
        }

        patcher = patch(
            "payments.payment_confirmation.stripe.StripeClient"
        )
        mock_client = patcher.start()
        self.addCleanup(patcher.stop)

        self.retrieve_session = (
            mock_client.return_value.v1.checkout.sessions.retrieve
        )
        self.retrieve_session.return_value = self.session

    def confirm(self):
        return confirm_order_payment(order_id=self.order.pk)

    def assert_order_remains_pending(self):
        self.order.refresh_from_db()
        self.part.refresh_from_db()

        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.assertIsNone(self.order.paid_at)
        self.assertIsNone(self.order.stripe_payment_intent_id)
        self.assertTrue(self.order.stock_reserved)
        self.assertEqual(self.part.stock, 3)

    def test_verified_payment_marks_order_paid_without_deducting_stock(self):
        self.assertTrue(self.confirm())

        self.order.refresh_from_db()
        self.part.refresh_from_db()

        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertIsNotNone(self.order.paid_at)
        self.assertEqual(
            self.order.stripe_payment_intent_id,
            "pi_test_confirmation",
        )
        self.assertEqual(self.part.stock, 3)
        self.assertEqual(self.order.items.count(), 1)
        self.retrieve_session.assert_called_once_with(
            "cs_test_confirmation",
        )

    def test_repeat_confirmation_preserves_timestamp_and_stock(self):
        self.assertTrue(self.confirm())
        self.order.refresh_from_db()
        original_paid_at = self.order.paid_at

        self.assertTrue(self.confirm())
        self.order.refresh_from_db()
        self.part.refresh_from_db()

        self.assertEqual(self.order.paid_at, original_paid_at)
        self.assertEqual(self.part.stock, 3)
        self.assertEqual(Order.objects.count(), 1)

    def test_unpaid_or_incomplete_sessions_do_not_mark_order_paid(self):
        states = [
            ("open", "unpaid"),
            ("complete", "unpaid"),
            ("expired", "unpaid"),
            ("open", "paid"),
        ]

        for status, payment_status in states:
            with self.subTest(
                status=status,
                payment_status=payment_status,
            ):
                self.retrieve_session.return_value = {
                    **self.session,
                    "status": status,
                    "payment_status": payment_status,
                }

                self.assertFalse(self.confirm())
                self.assert_order_remains_pending()

    def test_mismatched_session_details_are_rejected(self):
        changes = [
            {"id": "cs_test_other"},
            {"client_reference_id": "different-order"},
            {"livemode": True},
            {"mode": "subscription"},
            {"currency": "usd"},
            {"amount_total": 1},
        ]

        for values in changes:
            with self.subTest(values=values):
                self.retrieve_session.return_value = {
                    **self.session,
                    **values,
                }

                with self.assertRaises(CheckoutError):
                    self.confirm()

                self.assert_order_remains_pending()

    def test_missing_or_invalid_payment_intent_is_rejected(self):
        for payment_intent in (None, "", "invalid", {"id": "pi_other"}):
            with self.subTest(payment_intent=payment_intent):
                self.retrieve_session.return_value = {
                    **self.session,
                    "payment_intent": payment_intent,
                }

                with self.assertRaises(CheckoutError):
                    self.confirm()

                self.assert_order_remains_pending()

    def test_stripe_error_leaves_order_pending(self):
        self.retrieve_session.side_effect = stripe.APIConnectionError(
            "Simulated connection failure."
        )

        with self.assertRaises(CheckoutError):
            self.confirm()

        self.assert_order_remains_pending()

    def test_order_without_session_is_rejected_before_api_call(self):
        self.order.stripe_checkout_session_id = None
        self.order.save(update_fields=["stripe_checkout_session_id"])

        with self.assertRaises(CheckoutError):
            self.confirm()

        self.retrieve_session.assert_not_called()
        self.assert_order_remains_pending()

    def test_cancelled_or_unreserved_order_is_not_marked_paid(self):
        changes = [
            {
                "status": Order.Status.CANCELLED,
                "stock_reserved": False,
            },
            {
                "status": Order.Status.PENDING,
                "stock_reserved": False,
            },
        ]

        for values in changes:
            with self.subTest(values=values):
                Order.objects.filter(pk=self.order.pk).update(**values)

                with self.assertRaises(CheckoutError):
                    self.confirm()

                self.order.refresh_from_db()
                self.part.refresh_from_db()

                self.assertEqual(self.order.status, values["status"])
                self.assertIsNone(self.order.paid_at)
                self.assertIsNone(self.order.stripe_payment_intent_id)
                self.assertEqual(self.part.stock, 3)

    def test_order_change_during_api_call_is_rechecked(self):
        def cancel_during_retrieval(*args, **kwargs):
            Order.objects.filter(pk=self.order.pk).update(
                status=Order.Status.CANCELLED,
                stock_reserved=False,
            )
            return self.session

        self.retrieve_session.side_effect = cancel_during_retrieval

        with self.assertRaises(CheckoutError):
            self.confirm()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertIsNone(self.order.paid_at)

    def test_payment_intent_cannot_be_used_for_two_orders(self):
        Order.objects.create(
            full_name="Another Customer",
            email="another@example.com",
            phone="0871234567",
            address_line1="2 Test Street",
            town_or_city="Donegal",
            country="IE",
            total=Decimal("79.98"),
            stripe_payment_intent_id="pi_test_confirmation",
        )

        with self.assertRaises(CheckoutError):
            self.confirm()

        self.assert_order_remains_pending()

    def test_database_failure_rolls_back_payment_record(self):
        real_save = Order.save

        def save_then_fail(instance, *args, **kwargs):
            real_save(instance, *args, **kwargs)
            raise RuntimeError("Simulated database failure.")

        with patch.object(Order, "save", new=save_then_fail):
            with self.assertRaises(RuntimeError):
                self.confirm()

        self.assert_order_remains_pending()

        # Once the database works again, verification can be retried.
        self.assertTrue(self.confirm())

    def test_paid_order_rejects_a_different_payment_intent(self):
        self.assertTrue(self.confirm())
        self.order.refresh_from_db()
        original_paid_at = self.order.paid_at

        self.retrieve_session.return_value = {
            **self.session,
            "payment_intent": "pi_different_payment",
        }

        with self.assertRaises(CheckoutError):
            self.confirm()

        self.order.refresh_from_db()
        self.assertEqual(
            self.order.stripe_payment_intent_id,
            "pi_test_confirmation",
        )
        self.assertEqual(self.order.paid_at, original_paid_at)
