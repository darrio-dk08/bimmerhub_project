from django import forms


class BasketQuantityForm(forms.Form):
    """Accept a whole-number quantity within sensible limits."""

    quantity = forms.IntegerField(
        min_value=1,
        max_value=999,
        initial=1,
        label="Quantity",
    )