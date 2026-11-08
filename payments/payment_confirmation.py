import stripe

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Order
from .services import CheckoutError
from .stripe_checkout import _validate_session
from .stripe_data import stripe_to_dict


def confirm_order_payment(*, order_id):
    """Record a verified Stripe payment without deducting stock again."""
    snapshot = Order.objects.get(pk=order_id)
    session_id = snapshot.stripe_checkout_session_id

    if not session_id:
        raise CheckoutError("The order has no Stripe session to verify.")

    secret_key = settings.STRIPE_SECRET_KEY

    if not secret_key.startswith("sk_test_"):
        raise CheckoutError("Stripe sandbox configuration is required.")

    client = stripe.StripeClient(secret_key)

    # Retrieve payment information before locking the database row.
    try:
        session = client.v1.checkout.sessions.retrieve(session_id)
        session = stripe_to_dict(session)
    except stripe.StripeError as error:
        raise CheckoutError(
            "Stripe could not verify this payment. Please retry."
        ) from error

    try:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .get(pk=order_id)
            )

            if order.stripe_checkout_session_id != session_id:
                raise CheckoutError(
                    "The order's payment session changed during verification."
                )

            _validate_session(
                session,
                order,
                expected_id=session_id,
            )

            if (
                session.get("status") != "complete"
                or session.get("payment_status") != "paid"
            ):
                return False

            payment_intent_id = session.get("payment_intent")

            if (
                not isinstance(payment_intent_id, str)
                or not payment_intent_id.startswith("pi_")
                or len(payment_intent_id) > 255
            ):
                raise CheckoutError(
                    "Stripe did not return a valid payment identifier."
                )

            if order.stripe_payment_intent_id not in (
                None,
                "",
                payment_intent_id,
            ):
                raise CheckoutError(
                    "The payment identifier does not match this order."
                )

            # Repeated confirmations must not change the original timestamp.
            if order.status == Order.Status.PAID:
                if (
                    order.paid_at is None
                    or order.stripe_payment_intent_id != payment_intent_id
                ):
                    raise CheckoutError(
                        "The saved payment record needs investigation."
                    )
                return True

            if (
                order.status != Order.Status.PENDING
                or order.paid_at is not None
                or not order.stock_reserved
            ):
                raise CheckoutError(
                    "Payment was received for an order that needs "
                    "manual review. Its stock has not been changed."
                )

            order.stripe_payment_intent_id = payment_intent_id
            order.status = Order.Status.PAID
            order.paid_at = timezone.now()
            order.save(
                update_fields=[
                    "stripe_payment_intent_id",
                    "status",
                    "paid_at",
                    "updated_at",
                ],
            )

            # Stock was already deducted when the order was reserved.
            return True

    except IntegrityError as error:
        raise CheckoutError(
            "The payment could not be recorded. "
            "Please retry verification; do not pay again."
        ) from error