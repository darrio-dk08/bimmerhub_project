from django import forms

from .models import Order


class BasketQuantityForm(forms.Form):
    """Accept a whole-number quantity within sensible limits."""

    quantity = forms.IntegerField(
        min_value=1,
        max_value=999,
        initial=1,
        label="Quantity",
    )


class CheckoutForm(forms.ModelForm):
    """Collect contact details and an Irish delivery address."""

    country = forms.ChoiceField(
        choices=[("IE", "Ireland")],
        initial="IE",
        help_text="We currently deliver within Ireland only.",
    )

    class Meta:
        model = Order
        fields = [
            "full_name",
            "email",
            "phone",
            "address_line1",
            "address_line2",
            "town_or_city",
            "county",
            "postal_code",
            "country",
        ]
        labels = {
            "full_name": "Full name",
            "email": "Email address",
            "phone": "Phone number",
            "address_line1": "Address line 1",
            "address_line2": "Address line 2 (optional)",
            "town_or_city": "Town or city",
            "county": "County (optional)",
            "postal_code": "Eircode (optional)",
        }
        widgets = {
            "full_name": forms.TextInput(
                attrs={"autocomplete": "name"},
            ),
            "email": forms.EmailInput(
                attrs={"autocomplete": "email"},
            ),
            "phone": forms.TextInput(
                attrs={"type": "tel", "autocomplete": "tel"},
            ),
            "address_line1": forms.TextInput(
                attrs={"autocomplete": "address-line1"},
            ),
            "address_line2": forms.TextInput(
                attrs={"autocomplete": "address-line2"},
            ),
            "town_or_city": forms.TextInput(
                attrs={"autocomplete": "address-level2"},
            ),
            "county": forms.TextInput(
                attrs={"autocomplete": "address-level1"},
            ),
            "postal_code": forms.TextInput(
                attrs={"autocomplete": "postal-code"},
            ),
        }