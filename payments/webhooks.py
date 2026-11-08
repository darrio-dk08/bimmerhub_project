import logging

import stripe

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .checkout_recovery import recover_checkout_session
from .services import CheckoutError
from .stripe_data import stripe_to_dict


logger = logging.getLogger(__name__)

SUPPORTED_EVENTS = {
    "checkout.session.completed",
    "checkout.session.expired",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
}


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Verify Stripe's signature before reconciling a checkout session."""
    secret = settings.STRIPE_WEBHOOK_SECRET

    if not secret.startswith("whsec_"):
        logger.error("Stripe webhook signing secret is not configured.")
        return HttpResponse(status=503)

    signature = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=request.body,
            sig_header=signature,
            secret=secret,
            tolerance=300,

        )
        event = stripe_to_dict(event)
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)

    # This integration currently accepts sandbox events only.
    if event.get("livemode") is not False:
        return HttpResponse(status=400)

    if event.get("type") not in SUPPORTED_EVENTS:
        return HttpResponse(status=200)

    data = event.get("data")
    if not isinstance(data, dict):
        return HttpResponse(status=400)

    session = data.get("object")
    if not isinstance(session, dict):
        return HttpResponse(status=400)

    session_id = session.get("id")

    if (
        not isinstance(session_id, str)
        or not session_id.startswith("cs_test_")
        or len(session_id) > 255
    ):
        return HttpResponse(status=400)

    try:
        # Retrieve Stripe's current session state rather than trusting
        # the event's possibly older payment or expiry status.
        recover_checkout_session(session_id=session_id)
    except (CheckoutError, DatabaseError):
        logger.warning(
            "Stripe webhook reconciliation failed; "
            "returning a retryable response."
        )
        return HttpResponse(status=503)

    return HttpResponse(status=200)
