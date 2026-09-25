from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from .forms import VehicleForm
from .models import Vehicle


@login_required(login_url="account_login")
@require_safe
def vehicle_list(request):
    """Show only the signed-in user's vehicles."""
    vehicles = Vehicle.objects.filter(user=request.user).order_by(
        "make", "model", "pk"
    )

    return render(
        request,
        "garage/vehicle_list.html",
        {"vehicles": vehicles},
    )


@login_required(login_url="account_login")
@require_http_methods(["GET", "POST"])
def vehicle_create(request):
    """Add a vehicle belonging to the signed-in user."""
    form = VehicleForm(
        request.POST if request.method == "POST" else None
    )

    if request.method == "POST" and form.is_valid():
        vehicle = form.save(commit=False)
        vehicle.user = request.user
        vehicle.save()

        messages.success(request, "Vehicle added to your garage.")
        return redirect("garage:vehicle_list")

    return render(
        request,
        "garage/vehicle_form.html",
        {"form": form, "page_title": "Add a vehicle"},
    )


@login_required(login_url="account_login")
@require_http_methods(["GET", "POST"])
def vehicle_update(request, pk):
    """Allow users to edit only their own vehicles."""
    vehicle = get_object_or_404(
        Vehicle,
        pk=pk,
        user=request.user,
    )
    form = VehicleForm(
        request.POST if request.method == "POST" else None,
        instance=vehicle,
    )

    if request.method == "POST" and form.is_valid():
        if form.has_changed():
            form.save()
            messages.success(request, "Vehicle updated.")
        else:
            messages.info(request, "No changes were made.")

        return redirect("garage:vehicle_list")

    return render(
        request,
        "garage/vehicle_form.html",
        {"form": form, "page_title": "Edit vehicle"},
    )


@login_required(login_url="account_login")
@require_http_methods(["GET", "POST"])
def vehicle_delete(request, pk):
    """Show confirmation and delete an owned vehicle only on POST."""
    vehicle = get_object_or_404(
        Vehicle,
        pk=pk,
        user=request.user,
    )

    if request.method == "POST":
        vehicle.delete()
        messages.success(request, "Vehicle removed from your garage.")
        return redirect("garage:vehicle_list")

    return render(
        request,
        "garage/vehicle_confirm_delete.html",
        {"vehicle": vehicle},
    )