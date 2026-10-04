from .basket import BASKET_SESSION_KEY, get_basket_summary


def basket_count(request):
    """Show the quantity of existing products in the session basket."""
    if not request.session.get(BASKET_SESSION_KEY):
        return {"basket_item_count": 0}

    summary = get_basket_summary(request)

    return {
        "basket_item_count": sum(
            item["quantity"] for item in summary["items"]
        ),
    }