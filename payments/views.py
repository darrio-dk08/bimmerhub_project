from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe

from parts.models import Part

from .basket import BASKET_SESSION_KEY, get_basket_summary
from .forms import BasketQuantityForm, CheckoutForm
from .checkout_flow import current_payment, mark_basket_changed, save_review


@require_safe
def basket_detail(request):
    """Display the visitor's session basket."""
    return render(
        request,
        "payments/basket_detail.html",
        get_basket_summary(request),
    )


@require_POST
def basket_add(request, pk):
    """Add a quantity without exceeding current stock."""
    part = get_object_or_404(Part, pk=pk)
    form = BasketQuantityForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Enter a whole-number quantity from 1 to 999.")
        return redirect("parts:part_detail", pk=part.pk)

    basket = request.session.get(BASKET_SESSION_KEY, {}).copy()
    key = str(part.pk)
    quantity = basket.get(key, 0) + form.cleaned_data["quantity"]

    if quantity > part.stock or quantity > 999:
        messages.error(
            request,
            "That quantity exceeds the available stock or basket limit. "
            "Your basket has not changed.",
        )
        return redirect("parts:part_detail", pk=part.pk)

    basket[key] = quantity
    request.session[BASKET_SESSION_KEY] = basket
    mark_basket_changed(request)

    messages.success(request, f"{part.name} added to your basket.")
    return redirect("payments:basket_detail")


@require_POST
def basket_update(request, pk):
    """Replace the quantity of an existing basket item."""
    part = get_object_or_404(Part, pk=pk)
    basket = request.session.get(BASKET_SESSION_KEY, {}).copy()
    key = str(part.pk)

    if key not in basket:
        messages.error(request, "That part is not in your basket.")
        return redirect("payments:basket_detail")

    form = BasketQuantityForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Enter a whole-number quantity from 1 to 999.")
        return redirect("payments:basket_detail")

    quantity = form.cleaned_data["quantity"]

    if quantity > part.stock:
        messages.error(
            request,
            "That quantity exceeds the available stock. "
            "Reduce the quantity or remove the item.",
        )
        return redirect("payments:basket_detail")

    basket[key] = quantity
    request.session[BASKET_SESSION_KEY] = basket
    mark_basket_changed(request)

    messages.success(request, "Basket quantity updated.")
    return redirect("payments:basket_detail")


@require_POST
def basket_remove(request, pk):
    """Remove an item, including one deleted from the catalogue."""
    basket = request.session.get(BASKET_SESSION_KEY, {}).copy()
    key = str(pk)

    if key in basket:
        del basket[key]
        request.session[BASKET_SESSION_KEY] = basket
        mark_basket_changed(request)
        messages.success(request, "Item removed from your basket.")

    return redirect("payments:basket_detail")


@login_required(login_url="account_login")
@require_http_methods(["GET", "POST"])
def checkout(request):
    """Validate delivery details and display an order review."""
    active = current_payment(request)
    if active:
        return redirect("payments:payment_success", reference=active.reference)
    summary = get_basket_summary(request)
    basket = request.session.get(BASKET_SESSION_KEY, {})

    existing_keys = {
        str(item["part"].pk)
        for item in summary["items"]
    }

    if set(basket) != existing_keys:
        request.session[BASKET_SESSION_KEY] = {
            key: quantity
            for key, quantity in basket.items()
            if key in existing_keys
        }
        mark_basket_changed(request)
        messages.warning(
            request,
            "A product is no longer available and was removed. "
            "Please review your basket before continuing.",
        )
        return redirect("payments:basket_detail")

    if not summary["items"]:
        messages.info(request, "Add a product before continuing to checkout.")
        return redirect("payments:basket_detail")

    if any(not item["available"] for item in summary["items"]):
        messages.error(
            request,
            "Some quantities exceed the available stock. "
            "Please update your basket before continuing.",
        )
        return redirect("payments:basket_detail")

    initial = {
        "full_name": request.user.get_full_name(),
        "email": request.user.email,
        "country": "IE",
    }
    form = CheckoutForm(
        data=request.POST if request.method == "POST" else None,
        initial=initial,
    )

    context = {
        **summary,
        "form": form,
    }

    if request.method == "POST" and form.is_valid():
        context["delivery_details"] = form.cleaned_data
        context["checkout_token"] = save_review(
            request, summary, form.cleaned_data,
        )
        return render(
            request,
            "payments/checkout_review.html",
            context,
        )

    return render(
        request,
        "payments/checkout.html",
        context,
    )
