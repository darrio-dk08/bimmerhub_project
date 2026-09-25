from django import forms

from .models import Category


class PartFilterForm(forms.Form):
    """Validate public catalogue search and category filters."""

    q = forms.CharField(
        required=False,
        max_length=100,
        label="Search parts",
        widget=forms.TextInput(
            attrs={
                "type": "search",
                "placeholder": "Name, part number or BMW model",
            }
        ),
    )

    category = forms.ModelChoiceField(
        required=False,
        queryset=Category.objects.order_by("name"),
        empty_label="All categories",
        label="Category",
    )