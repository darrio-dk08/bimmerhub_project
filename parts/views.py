from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from .forms import PartFilterForm
from .models import Part


def part_list(request):
    """Display the catalogue with optional search and category filters."""
    parts = Part.objects.select_related("category").order_by("name", "pk")
    filter_form = PartFilterForm(request.GET)
    filters_active = False

    if filter_form.is_valid():
        query = filter_form.cleaned_data["q"]
        category = filter_form.cleaned_data["category"]
        filters_active = bool(query or category)

        if query:
            parts = parts.filter(
                Q(name__icontains=query)
                | Q(part_number__icontains=query)
                | Q(compatible_model__icontains=query)
            )

        if category:
            parts = parts.filter(category=category)
    else:
        parts = parts.none()
        filters_active = True

    return render(
        request,
        "parts/part_list.html",
        {
            "parts": parts,
            "filter_form": filter_form,
            "filters_active": filters_active,
        },
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