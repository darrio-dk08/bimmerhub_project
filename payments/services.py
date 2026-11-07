from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from parts.models import Part

from .forms import CheckoutForm
from .models import Order, OrderItem


class CheckoutError(Exception):
    """Describe a problem that prevents order creation."""


@transaction.atomic
def create_pending_order(*, user, basket, delivery_data):
    """Save an unpaid order using validated details and database prices."""
    if not user.is_authenticated or not user.is_active:
        raise CheckoutError("Please log in before placing an order.")

    form = CheckoutForm(data=delivery_data)

    if not form.is_valid():
        raise CheckoutError("Please check your delivery details.")

    if not isinstance(basket, dict) or not basket:
        raise CheckoutError("Your basket is empty or invalid.")

    quantities = {}

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
            raise CheckoutError(
                "Each product quantity must be a whole number from 1 to 999."
            )

        quantities[product_id] = quantity

    parts = list(
        Part.objects.filter(pk__in=quantities).order_by("pk")
    )

    if len(parts) != len(quantities):
        raise CheckoutError(
            "A product is no longer available. Please review your basket."
        )

    subtotal = Decimal("0.00")

    for part in parts:
        quantity = quantities[part.pk]

        if quantity > part.stock:
            raise CheckoutError(
                f"There is insufficient stock for {part.name}."
            )

        if part.price < Decimal("0.00"):
            raise CheckoutError(
                "A product price is invalid. Please contact us."
            )

        subtotal += part.price * quantity

    delivery_cost = Decimal(str(settings.DELIVERY_CHARGE))

    if not delivery_cost.is_finite() or delivery_cost < Decimal("0.00"):
        raise CheckoutError("The delivery charge is unavailable.")

    order = form.save(commit=False)
    order.user = user
    order.currency = "eur"
    order.delivery_cost = delivery_cost
    order.total = subtotal + delivery_cost
    order.status = Order.Status.PENDING

    try:
        order.full_clean()
    except ValidationError as error:
        raise CheckoutError(
            "The order details or total could not be accepted."
        ) from error

    order.save()

    for part in parts:
        OrderItem.objects.create(
            order=order,
            part=part,
            product_name=part.name,
            part_number=part.part_number,
            unit_price=part.price,
            quantity=quantities[part.pk],
        )

    return order