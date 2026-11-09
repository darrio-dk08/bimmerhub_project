"""Customer-owned, CSRF-protected payment actions."""
import logging

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .checkout_flow import reserve_review, track_payment
from .models import Order
from .payment_confirmation import confirm_order_payment
from .payment_lifecycle import release_expired_reservation
from .services import CheckoutError
from .stripe_checkout import _validate_session, get_checkout_url
from .stripe_data import stripe_to_dict

logger = logging.getLogger(__name__)


def _status(order):
    return redirect("payments:payment_success", reference=order.reference)


def _open_checkout(request, order):
    if order.status != Order.Status.PENDING:
        return _status(order)
    try:
        url = get_checkout_url(user=request.user, order_id=order.pk)
    except CheckoutError as error:
        messages.error(request, str(error))
        return _status(order)
    except DatabaseError:
        logger.exception("Payment session could not be saved for %s", order.pk)
        messages.error(
            request, "Payment could not be confirmed. Retry this same order; "
            "do not start another payment.",
        )
        return _status(order)
    response = redirect(url)
    response.status_code = 303
    return response


@login_required(login_url="account_login")
@require_POST
def payment_start(request):
    try:
        order, created = reserve_review(
            request, request.POST.get("checkout_token"),
        )
    except CheckoutError as error:
        messages.error(request, str(error))
        return redirect("payments:checkout")
    except DatabaseError:
        logger.exception("Checkout reservation could not be completed")
        messages.error(request, "Checkout is temporarily unavailable. Retry.")
        return redirect("payments:checkout")
    track_payment(request, order)
    # A different pending order must be shown for review, never paid silently.
    if str(order.checkout_token) != request.POST.get("checkout_token"):
        messages.info(request, "Please resolve your existing payment first.")
        return _status(order)
    return _open_checkout(request, order)


@login_required(login_url="account_login")
@require_POST
def payment_retry(request, reference):
    order = get_object_or_404(Order, reference=reference, user=request.user)
    track_payment(request, order)
    return _open_checkout(request, order)


@login_required(login_url="account_login")
@require_POST
def payment_cancel_confirm(request, reference):
    order = get_object_or_404(Order, reference=reference, user=request.user)
    if order.status != Order.Status.PENDING:
        return _status(order)
    try:
        if not order.stripe_checkout_session_id:
            raise CheckoutError(
                "The payment session is not yet confirmed. Retry this same "
                "order or contact support with the order reference."
            )
        if not settings.STRIPE_SECRET_KEY.startswith("sk_test_"):
            raise CheckoutError("Sandbox payment is not configured.")
        sessions = stripe.StripeClient(
            settings.STRIPE_SECRET_KEY,
        ).v1.checkout.sessions
        session = stripe_to_dict(
            sessions.retrieve(order.stripe_checkout_session_id),
        )
        _validate_session(
            session, order, expected_id=order.stripe_checkout_session_id,
        )
        if session.get("status") == "open":
            # Stripe refuses expiry if payment has completed in the meantime.
            sessions.expire(order.stripe_checkout_session_id)
        # Both services independently retrieve and verify Stripe state.
        if not confirm_order_payment(order_id=order.pk):
            release_expired_reservation(order_id=order.pk)
    except (CheckoutError, stripe.StripeError, DatabaseError):
        messages.error(
            request, "Cancellation could not be confirmed. Your reservation "
            "has been kept unless payment or expiry was already verified. "
            "Check payment status before trying again.",
        )
    return _status(order)
