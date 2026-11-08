from uuid import UUID

import stripe

from django.conf import settings
from django.db import IntegrityError, transaction

from .models import Order
from .payment_confirmation import confirm_order_payment
from .payment_lifecycle import release_expired_reservation
from .services import CheckoutError
from .stripe_checkout import _validate_session
from .stripe_data import stripe_to_dict


def recover_checkout_session(*, session_id):
    """Recover and reconcile a session using trusted Stripe data.

    Internal service: any customer-facing caller must separately
    enforce ownership before displaying order information.
    """
    if (
        not isinstance(session_id, str)
        or not session_id.startswith("cs_test_")
        or len(session_id) > 255
    ):
        raise CheckoutError("A valid sandbox session ID is required.")

    secret_key = settings.STRIPE_SECRET_KEY

    if not secret_key.startswith("sk_test_"):
        raise CheckoutError("Stripe sandbox configuration is required.")

    client = stripe.StripeClient(secret_key)

    try:
        session = client.v1.checkout.sessions.retrieve(session_id)
        session = stripe_to_dict(session)
    except stripe.StripeError as error:
        raise CheckoutError(
            "Stripe could not verify this session. "
            "The stock reservation has not been changed."
        ) from error

    try:
        reference = UUID(str(session.get("client_reference_id")))
    except (ValueError, TypeError, AttributeError) as error:
        raise CheckoutError(
            "The Stripe session has no valid order reference."
        ) from error

    try:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .filter(reference=reference)
                .first()
            )

            if order is None:
                raise CheckoutError(
                    "No local order matches this Stripe session."
                )

            _validate_session(
                session,
                order,
                expected_id=session_id,
            )

            metadata = session.get("metadata") or {}

            if metadata.get("order_reference") != str(order.reference):
                raise CheckoutError(
                    "The Stripe metadata does not match this order."
                )

            saved_id = order.stripe_checkout_session_id

            if saved_id and saved_id != session_id:
                raise CheckoutError(
                    "This order already has a different Stripe session. "
                    "Manual investigation is required."
                )

            if not saved_id:
                request_data = order.stripe_checkout_request

                if (
                    not isinstance(request_data, dict)
                    or not request_data
                    or request_data.get("client_reference_id")
                    != str(order.reference)
                    or not request_data.get("expires_at")
                    or request_data.get("expires_at")
                    != session.get("expires_at")
                ):
                    raise CheckoutError(
                        "The session does not match a saved checkout request."
                    )

                if (
                    order.status != Order.Status.PENDING
                    or order.paid_at is not None
                    or not order.stock_reserved
                ):
                    raise CheckoutError(
                        "This order cannot recover a session automatically. "
                        "Manual investigation is required."
                    )

                order.stripe_checkout_session_id = session_id
                order.save(
                    update_fields=[
                        "stripe_checkout_session_id",
                        "updated_at",
                    ],
                )

            order_id = order.pk

    except IntegrityError as error:
        raise CheckoutError(
            "The recovered session could not be linked to this order. "
            "Please retry verification."
        ) from error

    # These services retrieve Stripe's current state again and apply
    # their own database locks before changing payment or stock.
    if (
        session.get("status") == "complete"
        and session.get("payment_status") == "paid"
    ):
        confirm_order_payment(order_id=order_id)

    elif (
        session.get("status") == "expired"
        and session.get("payment_status") == "unpaid"
    ):
        release_expired_reservation(order_id=order_id)

    return Order.objects.get(pk=order_id)