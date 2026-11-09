"""Read-only customer order history, using saved order snapshots."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .models import Order


@never_cache
@login_required(login_url="account_login")
@require_safe
def order_list(request):
    """List only this customer's orders, newest first."""
    orders = Order.objects.filter(user=request.user).order_by(
        "-created_at", "-pk",
    )
    page = Paginator(orders, 20).get_page(request.GET.get("page"))
    return render(request, "payments/order_list.html", {"page_obj": page})


@never_cache
@login_required(login_url="account_login")
@require_safe
def order_detail(request, reference):
    """Show a customer's saved order, never live catalogue prices."""
    order = get_object_or_404(
        Order.objects.filter(user=request.user).prefetch_related("items"),
        reference=reference,
    )
    return render(request, "payments/order_detail.html", {"order": order})
