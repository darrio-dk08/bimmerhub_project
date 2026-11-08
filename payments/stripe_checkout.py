from decimal import Decimal
from urllib.parse import urlsplit

import stripe

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Order
from .services import CheckoutError
from .stripe_data import stripe_to_dict


def _to_cents(amount):
    """Convert an exact non-negative euro amount to integer cents."""
    amount = Decimal(amount)
    cents = amount * 100

    if (
        not amount.is_finite()
        or amount < 0
        or cents != cents.to_integral_value()
    ):
        raise CheckoutError("The order contains an invalid amount.")

    return int(cents)


def _build_request(order):
    """Build the Stripe request from saved order snapshots."""
    base_url = settings.STRIPE_RETURN_BASE_URL.rstrip("/")
    parsed = urlsplit(base_url)

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise CheckoutError("The payment return address is invalid.")

    if parsed.scheme == "http" and parsed.hostname not in (
        "127.0.0.1",
        "localhost",
    ):
        raise CheckoutError("The payment return address must use HTTPS.")

    items = list(order.items.order_by("pk"))

    # Stripe allows up to 100 payment-mode line items.
    # Keep one space available for delivery.
    if not items or len(items) > 99:
        raise CheckoutError("This order cannot be sent to checkout.")

    subtotal = sum(
        (item.unit_price * item.quantity for item in items),
        Decimal("0.00"),
    )

    if subtotal + order.delivery_cost != order.total:
        raise CheckoutError("The saved order total does not match its items.")

    if order.country != "IE" or order.currency != "eur":
        raise CheckoutError("This checkout supports Ireland and euros only.")

    line_items = []

    for item in items:
        if not 1 <= item.quantity <= 999:
            raise CheckoutError("The order contains an invalid quantity.")

        line_items.append({
            "price_data": {
                "currency": order.currency,
                "unit_amount": _to_cents(item.unit_price),
                "product_data": {
                    "name": item.product_name,
                },
            },
            "quantity": item.quantity,
        })

    if order.delivery_cost:
        line_items.append({
            "price_data": {
                "currency": order.currency,
                "unit_amount": _to_cents(order.delivery_cost),
                "product_data": {
                    "name": "Delivery within Ireland",
                },
            },
            "quantity": 1,
        })

    reference = str(order.reference)

    return {
        "mode": "payment",
        "payment_method_types": ["card"],
        "client_reference_id": reference,
        "customer_email": order.email,
        "metadata": {"order_reference": reference},
        "payment_intent_data": {
            "metadata": {"order_reference": reference},
        },
        "line_items": line_items,
        "success_url": (
            f"{base_url}/basket/payment/{reference}/success/"
            "?session_id={CHECKOUT_SESSION_ID}"
        ),
        "cancel_url": (
            f"{base_url}/basket/payment/{reference}/cancel/"
        ),
        "expires_at": int(timezone.now().timestamp()) + 3600,
    }


def _validate_session(session, order, expected_id=None):
    """Check Stripe's response belongs to this sandbox order."""
    session_id = session.get("id")

    if (
        not isinstance(session_id, str)
        or not session_id.startswith("cs_test_")
        or (expected_id is not None and session_id != expected_id)
        or session.get("livemode") is not False
        or session.get("mode") != "payment"
        or session.get("client_reference_id") != str(order.reference)
        or session.get("currency") != order.currency
        or session.get("amount_total") != _to_cents(order.total)
    ):
        raise CheckoutError("Stripe returned an unexpected payment session.")


def get_checkout_url(*, user, order_id):
    """Create or retrieve the same Stripe session for a reserved order."""
    if not user.is_authenticated or not user.is_active:
        raise CheckoutError("Please log in before continuing.")

    secret_key = settings.STRIPE_SECRET_KEY

    if not secret_key.startswith("sk_test_"):
        raise CheckoutError("A Stripe sandbox key is required.")

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .filter(pk=order_id, user=user)
            .first()
        )

        if order is None:
            raise CheckoutError("This order is not available.")

        if (
            order.status != Order.Status.PENDING
            or order.paid_at is not None
            or not order.stock_reserved
        ):
            raise CheckoutError("This order is not awaiting payment.")

        session_id = order.stripe_checkout_session_id

        if not session_id and not order.stripe_checkout_request:
            order.stripe_checkout_request = _build_request(order)
            order.save(
                update_fields=["stripe_checkout_request", "updated_at"],
            )

        request_data = order.stripe_checkout_request
        idempotency_key = f"bimmerhub-checkout-{order.reference}"

    client = stripe.StripeClient(secret_key)

    try:
        if session_id:
            session = client.v1.checkout.sessions.retrieve(session_id)
        else:
            # The fixed expiry must still be over 30 minutes away for
            # a new session. Stop automatic creation retries after
            # 25 minutes, leaving a small timing margin.
            retry_deadline = request_data["expires_at"] - 2100

            if timezone.now().timestamp() >= retry_deadline:
                raise CheckoutError(
                    "This payment attempt needs its status checked. "
                    "Please contact support before starting another payment."
                )

            session = client.v1.checkout.sessions.create(
                request_data,
                options={"idempotency_key": idempotency_key},
            )
    except stripe.StripeError as error:
        # A timeout does not prove that Stripe created nothing.
        # Preserve the request and reservation for a safe retry.
                raise CheckoutError(
            "Stripe could not confirm the payment session. "
            "Please retry this same order."
        ) from error

    session = stripe_to_dict(session)

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .get(pk=order_id, user=user)
        )

        _validate_session(
            session,
            order,
            expected_id=order.stripe_checkout_session_id,
        )

        if not order.stripe_checkout_session_id:
            order.stripe_checkout_session_id = session["id"]
            order.save(
                update_fields=[
                    "stripe_checkout_session_id",
                    "updated_at",
                ],
            )

        if (
            order.status != Order.Status.PENDING
            or order.paid_at is not None
            or not order.stock_reserved
        ):
            raise CheckoutError("This order is no longer awaiting payment.")

    if (
        session.get("status") != "open"
        or session.get("payment_status") != "unpaid"
    ):
        raise CheckoutError(
            "This payment session is no longer open. "
            "Its payment status must be checked."
        )

    checkout_url = session.get("url")
    parsed_url = urlsplit(checkout_url or "")

    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc != "checkout.stripe.com"
    ):
        raise CheckoutError("Stripe did not return a valid checkout address.")

    return checkout_url