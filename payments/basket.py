from decimal import Decimal

from django.conf import settings

from parts.models import Part


BASKET_SESSION_KEY = "basket"


def get_basket_summary(request):
    """Read current prices, availability and delivery costs."""
    basket = request.session.get(BASKET_SESSION_KEY, {})
    parts = Part.objects.filter(pk__in=basket.keys()).order_by("name", "pk")

    items = []
    total = Decimal("0.00")

    for part in parts:
        quantity = basket[str(part.pk)]
        subtotal = part.price * quantity

        items.append(
            {
                "part": part,
                "quantity": quantity,
                "subtotal": subtotal,
                "available": quantity <= part.stock,
            }
        )
        total += subtotal

    delivery_cost = (
        Decimal(settings.DELIVERY_CHARGE)
        if items
        else Decimal("0.00")
    )

    return {
        "items": items,
        "total": total,
        "delivery_cost": delivery_cost,
        "grand_total": total + delivery_cost,
    }