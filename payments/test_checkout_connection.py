from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

import stripe
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from parts.models import Category, Part

from .checkout_flow import REVIEW_KEY
from .models import Order


@override_settings(
    DELIVERY_CHARGE="30.00",
    STRIPE_SECRET_KEY="sk_test_connection_tests",
    STRIPE_RETURN_BASE_URL="http://127.0.0.1:8000",
)
class CheckoutConnectionTests(TestCase):
    """Exercise browser requests through real services with a mocked API."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="buyer")
        cls.other = get_user_model().objects.create_user(username="other")
        category = Category.objects.create(name="Filters")
        cls.part = Part.objects.create(
            category=category, name="Filter", part_number="CONNECT-1",
            compatible_model="F10", price=Decimal("24.99"), stock=5,
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["basket"] = {str(self.part.pk): 2}
        session.save()
        self.details = {
            "full_name": "Test Customer", "email": "customer@example.com",
            "phone": "0871234567", "address_line1": "1 Test Street",
            "address_line2": "", "town_or_city": "Donegal", "county": "",
            "postal_code": "", "country": "IE",
        }
        self.start_url = reverse("payments:payment_start")
        self.checkout_url = reverse("payments:checkout")
        patcher = patch("stripe.StripeClient")
        self.sdk = patcher.start()
        self.addCleanup(patcher.stop)
        self.sessions = self.sdk.return_value.v1.checkout.sessions
        self.sessions.create.side_effect = self.created_session
        self.sessions.retrieve.side_effect = lambda sid: self.sdk_object()
        self.remote_status = "open"
        self.remote_payment = "unpaid"
        self.review()

    def sdk_object(self):
        order = Order.objects.get()
        return stripe.StripeObject.construct_from({
            "id": "cs_test_browser", "livemode": False, "mode": "payment",
            "client_reference_id": str(order.reference), "currency": "eur",
            "amount_total": int(order.total * 100),
            "status": self.remote_status,
            "payment_status": self.remote_payment,
            "payment_intent": "pi_browser_test",
            "url": "https://checkout.stripe.com/c/pay/cs_test_browser",
        }, None)

    def created_session(self, params, *, options):
        return self.sdk_object()

    def review(self):
        response = self.client.post(self.checkout_url, self.details)
        self.assertEqual(response.status_code, 200)
        self.token = self.client.session[REVIEW_KEY]["token"]
        return response

    def pay(self, **extra):
        return self.client.post(self.start_url, {
            "checkout_token": self.token, **extra,
        })

    def status_url(self, name="payment_success"):
        return reverse("payments:" + name, kwargs={
            "reference": Order.objects.get().reference,
        })

    def assert_unreserved(self):
        self.assertFalse(Order.objects.exists())
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 5)
        self.sessions.create.assert_not_called()

    def test_review_button_has_token_and_creates_no_order(self):
        response = self.review()
        self.assertContains(response, "Continue to payment")
        self.assertContains(response, self.token)
        self.assert_unreserved()

    def test_start_uses_saved_address_prices_and_reserves_once(self):
        response = self.pay(total="0.01", country="GB", full_name="Forged")
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.url.startswith(
            "https://checkout.stripe.com/"))
        order = Order.objects.get()
        self.assertEqual(order.full_name, "Test Customer")
        self.assertEqual(order.country, "IE")
        self.assertEqual(order.total, Decimal("79.98"))
        self.assertEqual(order.status, Order.Status.PENDING)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 3)
        payload = self.sessions.create.call_args.args[0]
        self.assertEqual(payload["line_items"][0]["quantity"], 2)
        self.assertEqual(payload["line_items"][1]
                         ["price_data"]["unit_amount"], 3000)

    def test_price_change_rolls_back_order_and_stock(self):
        Part.objects.filter(pk=self.part.pk).update(price=Decimal("25.00"))
        response = self.pay()
        self.assertRedirects(response, self.checkout_url)
        self.assert_unreserved()

    @override_settings(DELIVERY_CHARGE="31.00")
    def test_delivery_change_rolls_back_order_and_stock(self):
        # setUp also sees the override; create a review at the old charge.
        with override_settings(DELIVERY_CHARGE="30.00"):
            self.review()
        self.pay()
        self.assert_unreserved()

    def test_offsetting_price_changes_are_rejected_even_with_same_total(self):
        second = Part.objects.create(
            category=self.part.category, name="Other", part_number="CONNECT-2",
            compatible_model="F10", price=Decimal("10.00"), stock=5,
        )
        session = self.client.session
        session["basket"] = {str(self.part.pk): 2, str(second.pk): 1}
        session.save()
        self.review()
        Part.objects.filter(pk=self.part.pk).update(price=Decimal("25.99"))
        Part.objects.filter(pk=second.pk).update(price=Decimal("8.00"))
        self.pay()
        self.assert_unreserved()
        second.refresh_from_db()
        self.assertEqual(second.stock, 5)

    def test_changed_basket_requires_new_review(self):
        self.client.post(
            reverse("payments:basket_update", args=[self.part.pk]),
            {"quantity": 1},
        )
        self.pay()
        self.assert_unreserved()

    def test_deleted_product_or_reduced_stock_creates_no_order(self):
        Part.objects.filter(pk=self.part.pk).update(stock=1)
        self.pay()
        self.assertFalse(Order.objects.exists())
        self.sessions.create.assert_not_called()
        self.part.delete()
        self.pay()
        self.assertFalse(Order.objects.exists())

    def test_missing_wrong_or_other_users_token_cannot_pay(self):
        for token in ("", "bad-token"):
            self.client.post(self.start_url, {"checkout_token": token})
        self.client.force_login(self.other)
        self.pay()
        self.assert_unreserved()

    def test_get_and_missing_csrf_are_rejected(self):
        self.assertEqual(self.client.get(self.start_url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.start_url).status_code, 403)
        self.assert_unreserved()

    def test_anonymous_payment_start_requires_login(self):
        self.client.logout()
        self.assertEqual(self.pay().status_code, 302)
        self.assert_unreserved()

    def test_repeated_start_reuses_order_even_when_stock_is_exhausted(self):
        Part.objects.filter(pk=self.part.pk).update(stock=2)
        self.pay()
        self.pay()
        self.assertEqual(Order.objects.count(), 1)
        self.sessions.create.assert_called_once()
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 0)

    def test_timeout_can_resume_same_request_after_price_change(self):
        self.sessions.create.side_effect = stripe.APIConnectionError("Timeout")
        response = self.pay()
        self.assertRedirects(response, self.status_url(),
                             fetch_redirect_response=False)
        first = deepcopy(self.sessions.create.call_args.args)
        options = deepcopy(self.sessions.create.call_args.kwargs)
        Part.objects.filter(pk=self.part.pk).update(price=Decimal("99.00"))
        self.sessions.create.side_effect = self.created_session
        response = self.client.post(self.status_url("payment_retry"))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(first, self.sessions.create.call_args.args)
        self.assertEqual(options, self.sessions.create.call_args.kwargs)
        self.assertEqual(Order.objects.count(), 1)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 3)

    def test_second_browser_review_cannot_create_second_pending_order(self):
        other_tab = Client()
        other_tab.force_login(self.user)
        session = other_tab.session
        session["basket"] = {str(self.part.pk): 1}
        session.save()
        other_tab.post(self.checkout_url, self.details)
        second_token = other_tab.session[REVIEW_KEY]["token"]
        self.pay()
        response = other_tab.post(
            self.start_url, {"checkout_token": second_token})
        self.assertRedirects(response, self.status_url(),
                             fetch_redirect_response=False)
        self.assertEqual(Order.objects.count(), 1)
        self.sessions.create.assert_called_once()

    def test_checkout_redirects_to_pending_payment_before_stock_check(self):
        Part.objects.filter(pk=self.part.pk).update(stock=2)
        self.pay()
        self.assertRedirects(
            self.client.get(self.checkout_url), self.status_url(),
            fetch_redirect_response=False,
        )

    def test_bad_configuration_rolls_back_reservation(self):
        with override_settings(STRIPE_RETURN_BASE_URL="http://unsafe.example"):
            self.pay()
        self.assert_unreserved()

    def test_verified_payment_clears_basket_only_once(self):
        self.pay()
        self.remote_status, self.remote_payment = "complete", "paid"
        response = self.client.get(self.status_url())
        self.assertContains(response, "Payment confirmed")
        order = Order.objects.get()
        paid_at = order.paid_at
        self.assertEqual(self.client.session["basket"], {})
        self.client.post(reverse("payments:basket_add", args=[self.part.pk]),
                         {"quantity": 1})
        self.client.get(self.status_url())
        self.assertEqual(self.client.session["basket"], {str(self.part.pk): 1})
        order.refresh_from_db()
        self.assertEqual(order.paid_at, paid_at)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 3)

    def test_basket_edited_away_and_back_is_preserved(self):
        self.pay()
        url = reverse("payments:basket_update", args=[self.part.pk])
        self.client.post(url, {"quantity": 1})
        self.client.post(url, {"quantity": 2})
        self.remote_status, self.remote_payment = "complete", "paid"
        self.client.get(self.status_url())
        self.assertEqual(self.client.session["basket"], {str(self.part.pk): 2})

    def test_unpaid_return_keeps_basket_and_stock_reserved(self):
        self.pay()
        self.client.get(self.status_url())
        self.assertEqual(self.client.session["basket"], {str(self.part.pk): 2})
        self.assertTrue(Order.objects.get().stock_reserved)

    def test_retry_and_cancel_require_owner_post_and_csrf(self):
        self.pay()
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        for name in ("payment_retry", "payment_cancel_confirm"):
            url = self.status_url(name)
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(csrf.post(url).status_code, 403)
            other = Client()
            other.force_login(self.other)
            self.assertEqual(other.post(url).status_code, 404)
        self.sessions.expire.assert_not_called()

    def test_cancel_post_expires_session_and_restores_stock_once(self):
        self.pay()

        def expire(sid):
            self.remote_status = "expired"
            return self.sdk_object()
        self.sessions.expire.side_effect = expire
        url = self.status_url("payment_cancel_confirm")
        self.client.post(url)
        self.client.post(url)
        order = Order.objects.get()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertFalse(order.stock_reserved)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 5)
        self.sessions.expire.assert_called_once()
        self.assertEqual(self.client.session["basket"], {str(self.part.pk): 2})

    def test_cancellation_does_not_release_completed_payment(self):
        self.pay()
        self.remote_status, self.remote_payment = "complete", "paid"
        self.client.post(self.status_url("payment_cancel_confirm"))
        self.assertEqual(Order.objects.get().status, Order.Status.PAID)
        self.sessions.expire.assert_not_called()
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 3)

    def test_cancel_timeout_keeps_reservation(self):
        self.pay()
        self.sessions.expire.side_effect = stripe.APIConnectionError("Timeout")
        self.client.post(self.status_url("payment_cancel_confirm"))
        self.assertTrue(Order.objects.get().stock_reserved)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 3)

    def test_return_get_never_expires_session(self):
        self.pay()
        self.client.get(self.status_url("payment_cancel"))
        self.sessions.expire.assert_not_called()
        self.assertEqual(Order.objects.get().status, Order.Status.PENDING)

    def test_missing_session_cancellation_does_not_release_stock(self):
        self.sessions.create.side_effect = stripe.APIConnectionError("Timeout")
        self.pay()
        self.client.post(self.status_url("payment_cancel_confirm"))
        self.sessions.expire.assert_not_called()
        self.assertTrue(Order.objects.get().stock_reserved)

    def test_replaced_review_token_is_rejected(self):
        old_token = self.token
        self.details["address_line1"] = "2 New Street"
        self.review()
        self.client.post(self.start_url, {"checkout_token": old_token})
        self.assert_unreserved()

    def test_paid_retry_does_not_open_stripe_again(self):
        self.pay()
        self.remote_status, self.remote_payment = "complete", "paid"
        self.client.get(self.status_url())
        self.sessions.reset_mock()
        self.client.post(self.status_url("payment_retry"))
        self.sessions.create.assert_not_called()
        self.sessions.retrieve.assert_not_called()

    def test_mismatched_session_cannot_be_cancelled(self):
        self.pay()
        incorrect = self.sdk_object().to_dict()
        incorrect["client_reference_id"] = "different-order"
        self.sessions.retrieve.side_effect = None
        response = stripe.StripeObject.construct_from(incorrect, None)
        self.sessions.retrieve.return_value = response
        self.client.post(self.status_url("payment_cancel_confirm"))
        self.sessions.expire.assert_not_called()
        self.assertTrue(Order.objects.get().stock_reserved)
