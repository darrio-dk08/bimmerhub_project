from django import forms
from django.utils import timezone

from .models import Vehicle


class VehicleForm(forms.ModelForm):
    """Validate the vehicle details that users can edit."""

    class Meta:
        model = Vehicle
        fields = ["make", "model", "year", "engine", "registration"]
        help_texts = {
            "model": "For example: F10 518d",
            "engine": "For example: 2.0 diesel",
            "registration": "Optional.",
        }

    def clean_year(self):
        year = self.cleaned_data["year"]
        maximum_year = timezone.now().year + 1

        if not 1886 <= year <= maximum_year:
            raise forms.ValidationError(
                f"Enter a year between 1886 and {maximum_year}."
            )

        return year