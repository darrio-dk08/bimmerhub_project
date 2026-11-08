import stripe


def stripe_to_dict(value):
    """Convert Stripe SDK responses to ordinary Python dictionaries."""
    if isinstance(value, stripe.StripeObject):
        return value.to_dict()

    if isinstance(value, dict):
        return value

    raise TypeError("Expected a Stripe object or dictionary.")