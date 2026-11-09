from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Order
from .services import CheckoutError


class PaymentReturnTests(TestCase):
    """Check ownership and truthful payment-return pages."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="return_customer",
        )
        cls.other_user = get_user_model().objects.create_user(
            username="other_return_customer",
        )
        cls.order = Order.objects.create(
            user=cls.user,
            full_name="Test Customer",
            email="customer@example.com",
            phone="0871234567",
            address_line1="1 Test Street",
            town_or_city="Donegal",
            country="IE",
            delivery_cost=Decimal("30.00"),
            total=Decimal("79.98"),
            stock_reserved=True,
            stripe_checkout_session_id="cs_test_return",
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.success_url = reverse(
            "payments:payment_success",
            kwargs={"reference": self.order.reference},
        )
        self.cancel_url = reverse(
            "payments:payment_cancel",
            kwargs={"reference": self.order.reference},
        )

        patcher = patch(
            "payments.payment_returns.confirm_order_payment",
            return_value=False,
        )
        self.confirm_payment = patcher.start()
        self.addCleanup(patcher.stop)
        release_patcher = patch(
            "payments.payment_returns.release_expired_reservation",
            return_value=False,
        )
        self.release_stock = release_patcher.start()
        self.addCleanup(release_patcher.stop)

    def test_login_is_required(self):
        self.client.logout()

        for url in (self.success_url, self.cancel_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(
                    reverse("account_login"),
                    response["Location"],
                )

        self.confirm_payment.assert_not_called()

    def test_another_customer_cannot_access_order(self):
        self.client.force_login(self.other_user)

        for url in (self.success_url, self.cancel_url):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

        self.confirm_payment.assert_not_called()

    def test_mismatched_session_is_rejected(self):
        response = self.client.get(
            self.success_url,
            {"session_id": "cs_test_someone_else"},
        )

        self.assertEqual(response.status_code, 400)
        self.confirm_payment.assert_not_called()

    def test_unconfirmed_payment_displays_pending(self):
        response = self.client.get(self.success_url)

        self.assertContains(response, "Payment confirmation pending")
        self.confirm_payment.assert_called_once_with(
            order_id=self.order.pk,
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)

    def test_verified_payment_displays_confirmation(self):
        def record_payment(*, order_id):
            Order.objects.filter(pk=order_id).update(
                status=Order.Status.PAID,
                paid_at=timezone.now(),
                stripe_payment_intent_id="pi_test_return",
            )
            return True

        self.confirm_payment.side_effect = record_payment

        response = self.client.get(self.success_url)

        self.assertContains(response, "Payment confirmed")
        self.assertContains(response, "79.98")

    def test_verification_error_does_not_claim_payment_failed(self):
        self.confirm_payment.side_effect = CheckoutError(
            "Simulated verification failure.",
        )

        response = self.client.get(self.success_url)

        self.assertContains(response, "Payment confirmation pending")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.assertTrue(self.order.stock_reserved)

    def test_cancel_return_does_not_cancel_or_release_order(self):
        response = self.client.get(self.cancel_url)

        self.assertContains(response, "You returned from payment")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.assertTrue(self.order.stock_reserved)
        self.assertIsNone(self.order.paid_at)
        self.confirm_payment.assert_not_called()

    def test_paid_order_is_shown_as_paid_on_both_pages(self):
        Order.objects.filter(pk=self.order.pk).update(
            status=Order.Status.PAID,
            paid_at=timezone.now(),
            stripe_payment_intent_id="pi_test_already_paid",
        )

        for url in (self.success_url, self.cancel_url):
            with self.subTest(url=url):
                self.assertContains(
                    self.client.get(url),
                    "Payment confirmed",
                )

        self.confirm_payment.assert_not_called()

    def test_missing_session_keeps_order_pending(self):
        Order.objects.filter(pk=self.order.pk).update(
            stripe_checkout_session_id=None,
        )

        response = self.client.get(self.success_url)

        self.assertContains(response, "Payment confirmation pending")
        self.confirm_payment.assert_not_called()

    def test_post_is_not_allowed(self):
        for url in (self.success_url, self.cancel_url):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 405)

        self.confirm_payment.assert_not_called()
