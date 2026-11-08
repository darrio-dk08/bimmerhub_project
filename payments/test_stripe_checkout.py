from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import stripe

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from parts.models import Category, Part

from .models import Order
from .reservations import reserve_pending_order
from .services import CheckoutError
from .stripe_checkout import get_checkout_url


@override_settings(
    DELIVERY_CHARGE="30.00",
    STRIPE_SECRET_KEY="sk_test_fake_key_for_unit_tests",
    STRIPE_RETURN_BASE_URL="http://127.0.0.1:8000",
)
class StripeCheckoutTests(TestCase):
    """Check session creation, saved prices and safe retries."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="stripe_customer",
        )
        cls.other_user = get_user_model().objects.create_user(
            username="other_stripe_customer",
        )
        category = Category.objects.create(name="Filters")
        cls.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter.",
            part_number="STRIPE-FILTER-001",
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

        self.session = {
            "id": "cs_test_checkout",
            "livemode": False,
            "mode": "payment",
            "client_reference_id": str(self.order.reference),
            "currency": "eur",
            "amount_total": 7998,
            "status": "open",
            "payment_status": "unpaid",
            "url": "https://checkout.stripe.com/c/pay/cs_test_checkout",
        }

        patcher = patch("payments.stripe_checkout.stripe.StripeClient")
        self.mock_client_class = patcher.start()
        self.addCleanup(patcher.stop)

        sessions = (
            self.mock_client_class.return_value.v1.checkout.sessions
        )
        self.create_session = sessions.create
        self.retrieve_session = sessions.retrieve
        self.create_session.return_value = self.session
        self.retrieve_session.return_value = self.session

    def checkout(self, user=None):
        return get_checkout_url(
            user=user or self.user,
            order_id=self.order.pk,
        )

    def test_creates_session_with_saved_prices_and_delivery(self):
        url = self.checkout()

        payload = self.create_session.call_args.args[0]
        options = self.create_session.call_args.kwargs["options"]
        lines = payload["line_items"]

        self.assertEqual(url, self.session["url"])
        self.assertEqual(
            lines[0]["price_data"]["unit_amount"],
            2499,
        )
        self.assertEqual(lines[0]["quantity"], 2)
        self.assertEqual(
            lines[1]["price_data"]["unit_amount"],
            3000,
        )
        self.assertEqual(lines[1]["quantity"], 1)
        self.assertEqual(
            payload["client_reference_id"],
            str(self.order.reference),
        )
        self.assertEqual(
            options["idempotency_key"],
            f"bimmerhub-checkout-{self.order.reference}",
        )

        self.order.refresh_from_db()
        self.assertEqual(
            self.order.stripe_checkout_session_id,
            "cs_test_checkout",
        )
        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.assertIsNone(self.order.paid_at)

    def test_existing_session_is_retrieved_not_created_again(self):
        first_url = self.checkout()
        second_url = self.checkout()

        self.assertEqual(first_url, second_url)
        self.create_session.assert_called_once()
        self.retrieve_session.assert_called_once_with(
            "cs_test_checkout",
        )

    def test_timeout_retry_uses_identical_request_and_key(self):
        self.create_session.side_effect = [
            stripe.APIConnectionError("Simulated timeout."),
            self.session,
        ]

        with self.assertRaises(CheckoutError):
            self.checkout()

        first_args = deepcopy(self.create_session.call_args.args)
        first_kwargs = deepcopy(self.create_session.call_args.kwargs)

        self.order.refresh_from_db()
        self.part.refresh_from_db()

        self.assertIsNone(self.order.stripe_checkout_session_id)
        self.assertTrue(self.order.stock_reserved)
        self.assertEqual(self.part.stock, 3)

        self.assertEqual(self.checkout(), self.session["url"])
        self.assertEqual(
            first_args,
            self.create_session.call_args.args,
        )
        self.assertEqual(
            first_kwargs,
            self.create_session.call_args.kwargs,
        )
        self.assertEqual(Order.objects.count(), 1)

    def test_catalogue_price_change_does_not_change_saved_order_price(self):
        self.part.price = Decimal("99.00")
        self.part.save(update_fields=["price"])

        self.checkout()

        payload = self.create_session.call_args.args[0]

        self.assertEqual(
            payload["line_items"][0]["price_data"]["unit_amount"],
            2499,
        )

    def test_other_user_cannot_create_session_for_order(self):
        with self.assertRaises(CheckoutError):
            self.checkout(user=self.other_user)

        self.create_session.assert_not_called()
        self.retrieve_session.assert_not_called()

    def test_paid_cancelled_or_unreserved_order_is_rejected(self):
        changes = [
            {"status": Order.Status.PAID},
            {"status": Order.Status.CANCELLED},
            {"stock_reserved": False},
        ]

        for values in changes:
            with self.subTest(values=values):
                Order.objects.filter(pk=self.order.pk).update(
                    status=Order.Status.PENDING,
                    stock_reserved=True,
                )
                Order.objects.filter(pk=self.order.pk).update(**values)

                with self.assertRaises(CheckoutError):
                    self.checkout()

        self.create_session.assert_not_called()

    def test_old_unknown_attempt_is_not_created_again(self):
        self.create_session.side_effect = stripe.APIConnectionError(
            "Simulated timeout."
        )

        with self.assertRaises(CheckoutError):
            self.checkout()

        future = timezone.now() + timedelta(minutes=26)

        with patch(
            "payments.stripe_checkout.timezone.now",
            return_value=future,
        ):
            with self.assertRaises(CheckoutError):
                self.checkout()

        self.assertEqual(self.create_session.call_count, 1)
        self.order.refresh_from_db()
        self.assertTrue(self.order.stock_reserved)

    def test_unexpected_stripe_response_is_rejected(self):
        self.create_session.return_value = {
            **self.session,
            "client_reference_id": str(uuid4()),
        }

        with self.assertRaises(CheckoutError):
            self.checkout()

        self.order.refresh_from_db()
        self.assertIsNone(self.order.stripe_checkout_session_id)
        self.assertEqual(self.order.status, Order.Status.PENDING)

    def test_failed_session_id_save_can_retry_same_stripe_request(self):
        real_save = Order.save

        def fail_session_save(instance, *args, **kwargs):
            if instance.stripe_checkout_session_id:
                raise RuntimeError("Simulated database failure.")
            return real_save(instance, *args, **kwargs)

        with patch.object(Order, "save", new=fail_session_save):
            with self.assertRaises(RuntimeError):
                self.checkout()

        first_args = deepcopy(self.create_session.call_args.args)
        first_kwargs = deepcopy(self.create_session.call_args.kwargs)

        self.order.refresh_from_db()
        self.assertIsNone(self.order.stripe_checkout_session_id)
        self.assertTrue(self.order.stripe_checkout_request)

        self.assertEqual(self.checkout(), self.session["url"])
        self.assertEqual(
            first_args,
            self.create_session.call_args.args,
        )
        self.assertEqual(
            first_kwargs,
            self.create_session.call_args.kwargs,
        )
