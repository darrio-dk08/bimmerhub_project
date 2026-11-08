import stripe

from django.conf import settings
from django.db import transaction
from django.db.models import F

from parts.models import Part

from .models import Order
from .services import CheckoutError
from .stripe_data import stripe_to_dict


def release_expired_reservation(*, order_id):
    """Restore stock once after Stripe confirms an unpaid session expired."""
    snapshot = Order.objects.get(pk=order_id)

    if (
        snapshot.status != Order.Status.PENDING
        or snapshot.paid_at is not None
        or not snapshot.stock_reserved
    ):
        return False

    session_id = snapshot.stripe_checkout_session_id

    if not session_id:
        raise CheckoutError(
            "The order has no Stripe session to verify."
        )

    secret_key = settings.STRIPE_SECRET_KEY

    if not secret_key.startswith("sk_test_"):
        raise CheckoutError(
            "Stripe sandbox configuration is required."
        )

    client = stripe.StripeClient(secret_key)

    # Keep the network request outside the database transaction.
    try:
        session = client.v1.checkout.sessions.retrieve(session_id)
        session = stripe_to_dict(session)
    except stripe.StripeError as error:
        raise CheckoutError(
            "Stripe could not verify the payment session. "
            "Reserved stock has not been released."
        ) from error

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .get(pk=order_id)
        )

        # Another request may have changed the order during the API call.
        if (
            order.status != Order.Status.PENDING
            or order.paid_at is not None
            or not order.stock_reserved
        ):
            return False

        if (
            order.stripe_checkout_session_id != session_id
            or session.get("id") != session_id
            or session.get("client_reference_id") != str(order.reference)
            or session.get("livemode") is not False
            or session.get("mode") != "payment"
            or session.get("currency") != order.currency
            or session.get("amount_total") != int(order.total * 100)
        ):
            raise CheckoutError(
                "The Stripe session does not match this order."
            )

        if (
            session.get("status") != "expired"
            or session.get("payment_status") != "unpaid"
        ):
            return False

        for item in order.items.order_by("part_id"):
            # A deleted catalogue product has nothing to restock.
            if item.part_id is not None:
                Part.objects.filter(pk=item.part_id).update(
                    stock=F("stock") + item.quantity,
                )

        order.stock_reserved = False
        order.status = Order.Status.CANCELLED
        order.save(
            update_fields=[
                "stock_reserved",
                "status",
                "updated_at",
            ],
        )

        return True
