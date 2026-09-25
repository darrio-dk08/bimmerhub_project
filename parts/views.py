from django.shortcuts import get_object_or_404, render

from .models import Part


def part_list(request):
    """Display the public BMW parts catalogue."""
    parts = Part.objects.select_related("category").order_by("name", "pk")

    return render(
        request,
        "parts/part_list.html",
        {"parts": parts},
    )


def part_detail(request, pk):
    """Display one product or return 404 when it does not exist."""
    part = get_object_or_404(
        Part.objects.select_related("category"),
        pk=pk,
    )

    return render(
        request,
        "parts/part_detail.html",
        {"part": part},
    )
