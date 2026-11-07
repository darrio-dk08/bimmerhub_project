from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import F

from parts.models import Part

from .forms import CheckoutForm
from .models import Order
from .services import CheckoutError, create_pending_order


def reserve_pending_order(
    *,
    user,
    basket,
    delivery_data,
    checkout_token,
):
    """Create one unpaid order and reserve stock once per checkout token."""
    if not user.is_authenticated or not user.is_active:
        raise CheckoutError("Please log in before placing an order.")

    try:
        token = UUID(str(checkout_token))
    except (ValueError, TypeError, AttributeError) as error:
        raise CheckoutError("Please restart checkout.") from error

    form = CheckoutForm(data=delivery_data)

    if not form.is_valid():
        raise CheckoutError("Please check your delivery details.")

    if not isinstance(basket, dict) or not basket:
        raise CheckoutError("Your basket is empty or invalid.")

    for key, quantity in basket.items():
        if (
            not isinstance(key, str)
            or not key.isascii()
            or not key.isdigit()
            or len(key) > 19
        ):
            raise CheckoutError("Your basket contains an invalid product.")

        product_id = int(key)

        if (
            product_id < 1
            or product_id > 9223372036854775807
            or str(product_id) != key
        ):
            raise CheckoutError("Your basket contains an invalid product.")

        if type(quantity) is not int or not 1 <= quantity <= 999:
            raise CheckoutError("Your basket contains an invalid quantity.")

    try:
        with transaction.atomic():
            # PostgreSQL serializes checkout attempts for this customer.
            locked_user = (
                get_user_model()
                .objects.select_for_update()
                .get(pk=user.pk)
            )

            if not locked_user.is_active:
                raise CheckoutError("Please log in before placing an order.")

            existing = (
                Order.objects.select_for_update()
                .filter(checkout_token=token)
                .first()
            )

            if existing is not None:
                return _reuse_order(
                    existing,
                    locked_user,
                    basket,
                    form.cleaned_data,
                )

            order = create_pending_order(
                user=locked_user,
                basket=basket,
                delivery_data=form.cleaned_data,
            )

            # The database uniqueness constraint also protects the token.
            order.checkout_token = token
            order.save(update_fields=["checkout_token", "updated_at"])

            for item in order.items.order_by("part_id"):
                updated = Part.objects.filter(
                    pk=item.part_id,
                    stock__gte=item.quantity,
                ).update(
                    stock=F("stock") - item.quantity,
                )

                if updated != 1:
                    raise CheckoutError(
                        "Stock changed during checkout. "
                        "Please review your basket."
                    )

            order.stock_reserved = True
            order.save(update_fields=["stock_reserved", "updated_at"])

            return order

    except IntegrityError as error:
        # Any order, items and stock changes in this attempt roll back.
        raise CheckoutError(
            "Checkout could not be completed. Please retry your checkout."
        ) from error


def _reuse_order(order, user, basket, delivery_details):
    """Allow an identical retry only for the original customer."""
    if order.user_id != user.pk:
        raise CheckoutError("Please restart checkout.")

    if order.status != Order.Status.PENDING or not order.stock_reserved:
        raise CheckoutError("This checkout attempt is no longer available.")

    saved_basket = {
        str(item.part_id): item.quantity
        for item in order.items.all()
    }

    if saved_basket != basket:
        raise CheckoutError(
            "Your basket has changed. Please start a new checkout."
        )

    for field in CheckoutForm.Meta.fields:
        if getattr(order, field) != delivery_details[field]:
            raise CheckoutError(
                "Your delivery details changed. Please start a new checkout."
            )

    return order