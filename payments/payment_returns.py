from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from .models import Order
from .payment_confirmation import confirm_order_payment
from .services import CheckoutError


def _render_payment_status(request, order, *, returned_from_cancel=False):
    """Display saved payment status without assuming payment succeeded."""
    return render(
        request,
        "payments/payment_status.html",
        {
            "order": order,
            "returned_from_cancel": returned_from_cancel,
        },
    )


@login_required(login_url="account_login")
@require_GET
def payment_success(request, reference):
    """Verify payment for an order belonging to the signed-in customer."""
    order = get_object_or_404(
        Order,
        reference=reference,
        user=request.user,
    )

    supplied_session_id = request.GET.get("session_id")

    # Never use an arbitrary session ID from the browser to confirm payment.
    if (
        supplied_session_id
        and order.stripe_checkout_session_id
        and supplied_session_id != order.stripe_checkout_session_id
    ):
        return HttpResponseBadRequest("The payment session does not match.")

    if (
        order.status == Order.Status.PENDING
        and order.stripe_checkout_session_id
    ):
        try:
            confirm_order_payment(order_id=order.pk)
        except CheckoutError:
            # A failed verification is not proof that payment failed.
            # Keep the existing order and let the customer check again.
            pass

    order.refresh_from_db()
    return _render_payment_status(request, order)


@login_required(login_url="account_login")
@require_GET
def payment_cancel(request, reference):
    """Returning from Stripe does not itself cancel or release an order."""
    order = get_object_or_404(
        Order,
        reference=reference,
        user=request.user,
    )

    return _render_payment_status(
        request,
        order,
        returned_from_cancel=True,
    )