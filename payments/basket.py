from decimal import Decimal

from parts.models import Part


BASKET_SESSION_KEY = "basket"


def get_basket_summary(request):
    """Read current prices and availability from the database."""
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

    return {
        "items": items,
        "total": total,
    }