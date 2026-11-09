"""Server-held checkout reviews and their connection to reserved orders."""
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from .basket import BASKET_SESSION_KEY
from .models import Order
from .reservations import reserve_pending_order
from .services import CheckoutError
from .stripe_checkout import _build_request

REVIEW_KEY = "checkout_review"
REVISION_KEY = "basket_revision"
ACTIVE_KEY = "active_payment_reference"
TRACKING_KEY = "payment_baskets"


def mark_basket_changed(request):
    """Track basket edits even when quantities return to their old values."""
    request.session[REVISION_KEY] = str(uuid4())


def save_review(request, summary, delivery_data):
    """Store trusted amounts and address; accept only a token from the form."""
    review = {
        "user_id": request.user.pk,
        "basket": request.session.get(BASKET_SESSION_KEY, {}).copy(),
        "revision": request.session.get(REVISION_KEY),
        "prices": {
            str(item["part"].pk): str(item["part"].price)
            for item in summary["items"]
        },
        "delivery_cost": str(summary["delivery_cost"]),
        "total": str(summary["grand_total"]),
        "delivery_data": dict(delivery_data),
    }
    previous = request.session.get(REVIEW_KEY, {})
    previous_data = {k: v for k, v in previous.items() if k != "token"}
    review["token"] = (
        previous["token"] if previous_data == review else str(uuid4())
    )
    request.session[REVIEW_KEY] = review
    return review["token"]


def current_payment(request):
    """Find an unfinished attempt before creating a new review/order."""
    reference = request.session.get(ACTIVE_KEY)
    if reference:
        order = Order.objects.filter(
            user=request.user, reference=reference,
        ).first()
        if order and order.status in (Order.Status.PENDING, Order.Status.PAID):
            return order
        request.session.pop(ACTIVE_KEY, None)
    return Order.objects.filter(
        user=request.user, status=Order.Status.PENDING, stock_reserved=True,
    ).first()


def reserve_review(request, token):
    """Check the review and reserve atomically, before making network calls."""
    review = request.session.get(REVIEW_KEY)
    if (
        not isinstance(review, dict)
        or not token
        or token != review.get("token")
        or review.get("user_id") != request.user.pk
    ):
        raise CheckoutError("Please review your delivery details again.")

    with transaction.atomic():
        # Use the same customer lock as the reservation service. Different
        # review tokens from multiple tabs cannot reserve two pending orders.
        user = get_user_model().objects.select_for_update().get(
            pk=request.user.pk,
        )
        if not user.is_active:
            raise CheckoutError("Please log in before continuing.")
        existing = Order.objects.filter(
            checkout_token=token, user=user,
        ).first()
        if existing:
            return existing, False
        pending = Order.objects.filter(
            user=user, status=Order.Status.PENDING, stock_reserved=True,
        ).first()
        if pending:
            return pending, False
        if (
            request.session.get(BASKET_SESSION_KEY, {}) != review["basket"]
            or request.session.get(REVISION_KEY) != review["revision"]
        ):
            raise CheckoutError("Your basket changed. Please review it again.")
        if not settings.STRIPE_SECRET_KEY.startswith("sk_test_"):
            raise CheckoutError("Sandbox payment is not configured.")

        order = reserve_pending_order(
            user=user,
            basket=review["basket"],
            delivery_data=review["delivery_data"],
            checkout_token=token,
        )
        prices = {
            str(item.part_id): str(item.unit_price)
            for item in order.items.all()
        }
        if (
            prices != review["prices"]
            or str(order.delivery_cost) != review["delivery_cost"]
            or str(order.total) != review["total"]
        ):
            # Raising outside the nested reservation transaction also rolls
            # back the new order, its items and every stock deduction.
            raise CheckoutError(
                "Prices or delivery changed. Please review the new amounts "
                "before continuing. No order was created."
            )
        # Validate configuration and persist the exact Stripe request before
        # committing the reservation. Never call Stripe inside this lock.
        order.stripe_checkout_request = _build_request(order)
        order.save(update_fields=["stripe_checkout_request", "updated_at"])
    return order, True


def track_payment(request, order):
    request.session[ACTIVE_KEY] = str(order.reference)
    review = request.session.get(REVIEW_KEY, {})
    if review.get("token") != str(order.checkout_token):
        return
    tracking = request.session.get(TRACKING_KEY, {}).copy()
    tracking.setdefault(str(order.reference), {
        "basket": review["basket"], "revision": review["revision"],
    })
    request.session[TRACKING_KEY] = tracking


def finish_basket(request, order):
    """Clear only the unchanged purchased basket, once, after verified pay."""
    if order.status not in (Order.Status.PAID, Order.Status.CANCELLED):
        return
    reference = str(order.reference)
    tracking = request.session.get(TRACKING_KEY, {}).copy()
    snapshot = tracking.pop(reference, None)
    if snapshot:
        if (
            order.status == Order.Status.PAID
            and request.session.get(BASKET_SESSION_KEY, {})
            == snapshot["basket"]
            and request.session.get(REVISION_KEY) == snapshot["revision"]
        ):
            request.session[BASKET_SESSION_KEY] = {}
            mark_basket_changed(request)
        request.session[TRACKING_KEY] = tracking
    if request.session.get(ACTIVE_KEY) == reference:
        request.session.pop(ACTIVE_KEY, None)
    review = request.session.get(REVIEW_KEY, {})
    if review.get("token") == str(order.checkout_token):
        request.session.pop(REVIEW_KEY, None)
