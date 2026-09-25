from django.shortcuts import render

from .models import Part


def part_list(request):
    """Display the public BMW parts catalogue."""
    parts = Part.objects.select_related("category").order_by("name", "pk")

    return render(
        request,
        "parts/part_list.html",
        {"parts": parts},
    )