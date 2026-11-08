import hashlib
import hmac
import json
import time
from unittest.mock import patch

from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .services import CheckoutError


TEST_WEBHOOK_SECRET = "whsec_fake_secret_for_unit_tests"


@override_settings(
    STRIPE_WEBHOOK_SECRET=TEST_WEBHOOK_SECRET,
)
class StripeWebhookTests(TestCase):
    """Check webhook signatures, routing and retry responses."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.url = reverse("payments:stripe_webhook")

        self.event = {
            "id": "evt_test_webhook",
            "object": "event",
            "livemode": False,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_webhook",
                    "object": "checkout.session",
                },
            },
        }

        patcher = patch(
            "payments.webhooks.recover_checkout_session"
        )
        self.recover = patcher.start()
        self.addCleanup(patcher.stop)

    def make_payload(self, event=None):
        return json.dumps(
            self.event if event is None else event,
            separators=(",", ":"),
        ).encode("utf-8")

    def make_signature(self, payload, timestamp=None):
        if timestamp is None:
            timestamp = int(time.time())

        signed_payload = (
            str(timestamp).encode("utf-8") + b"." + payload
        )
        digest = hmac.new(
            TEST_WEBHOOK_SECRET.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        return f"t={timestamp},v1={digest}"

    def post_payload(self, payload, signature):
        return self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=signature,
        )

    def post_event(self, event=None):
        payload = self.make_payload(event)
        return self.post_payload(
            payload,
            self.make_signature(payload),
        )

    def test_supported_events_accept_valid_signatures_without_csrf(self):
        event_types = [
            "checkout.session.completed",
            "checkout.session.expired",
            "checkout.session.async_payment_succeeded",
            "checkout.session.async_payment_failed",
        ]

        self.assertEqual(self.url, "/basket/webhook/")

        for event_type in event_types:
            with self.subTest(event_type=event_type):
                self.recover.reset_mock()
                event = {**self.event, "type": event_type}

                response = self.post_event(event)

                self.assertEqual(response.status_code, 200)
                self.recover.assert_called_once_with(
                    session_id="cs_test_webhook",
                )

    def test_missing_or_invalid_signature_is_rejected(self):
        payload = self.make_payload()

        for signature in ("", "invalid", "t=123,v1=incorrect"):
            with self.subTest(signature=signature):
                response = self.post_payload(payload, signature)

                self.assertEqual(response.status_code, 400)

        self.recover.assert_not_called()

    def test_modified_body_invalidates_signature(self):
        original = self.make_payload()
        signature = self.make_signature(original)
        modified = original.replace(
            b"cs_test_webhook",
            b"cs_test_changed",
        )

        response = self.post_payload(modified, signature)

        self.assertEqual(response.status_code, 400)
        self.recover.assert_not_called()

    def test_old_signature_is_rejected(self):
        payload = self.make_payload()
        signature = self.make_signature(
            payload,
            timestamp=int(time.time()) - 600,
        )

        response = self.post_payload(payload, signature)

        self.assertEqual(response.status_code, 400)
        self.recover.assert_not_called()

    def test_invalid_json_is_rejected(self):
        payload = b"{invalid-json"

        response = self.post_payload(
            payload,
            self.make_signature(payload),
        )

        self.assertEqual(response.status_code, 400)
        self.recover.assert_not_called()

    def test_unhandled_event_is_acknowledged_without_recovery(self):
        event = {
            **self.event,
            "type": "customer.created",
        }

        response = self.post_event(event)

        self.assertEqual(response.status_code, 200)
        self.recover.assert_not_called()

    def test_live_event_is_rejected(self):
        event = {
            **self.event,
            "livemode": True,
        }

        response = self.post_event(event)

        self.assertEqual(response.status_code, 400)
        self.recover.assert_not_called()

    def test_processing_failure_can_be_retried(self):
        errors = [
            CheckoutError("Simulated Stripe verification failure."),
            OperationalError("Simulated database failure."),
        ]

        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.recover.reset_mock()
                self.recover.side_effect = [error, None]

                with self.assertLogs(
                    "payments.webhooks",
                    level="WARNING",
                ):
                    first_response = self.post_event()

                second_response = self.post_event()

                self.assertEqual(first_response.status_code, 503)
                self.assertEqual(second_response.status_code, 200)
                self.assertEqual(self.recover.call_count, 2)

    @override_settings(STRIPE_WEBHOOK_SECRET="")
    def test_missing_signing_secret_returns_service_unavailable(self):
        with self.assertLogs(
            "payments.webhooks",
            level="ERROR",
        ):
            response = self.post_event()

        self.assertEqual(response.status_code, 503)
        self.recover.assert_not_called()

    def test_get_request_is_not_allowed(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.recover.assert_not_called()