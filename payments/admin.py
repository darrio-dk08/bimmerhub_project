from django.contrib import admin

from .models import Order, OrderItem


class ReadOnlyOrderPermissions:
    """Keep all order mutations in payment services, even for superusers."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(ReadOnlyOrderPermissions, admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = (
        "product_name", "part_number", "unit_price", "quantity", "subtotal",
    )
    readonly_fields = fields

    def has_view_permission(self, request, obj=None):
        # Permission to inspect an order includes its saved line items.
        return (
            request.user.has_perm("payments.view_order")
            or request.user.has_perm("payments.change_order")
        )


@admin.register(Order)
class OrderAdmin(ReadOnlyOrderPermissions, admin.ModelAdmin):
    list_display = (
        "reference", "created_at", "full_name", "email", "status",
        "total", "currency", "stock_reserved",
    )
    list_filter = ("status", "stock_reserved", "created_at")
    search_fields = (
        "=reference", "full_name", "email", "=stripe_checkout_session_id",
        "=stripe_payment_intent_id",
    )
    ordering = ("-created_at", "-pk")
    list_per_page = 25
    list_select_related = ("user",)
    actions = None
    readonly_fields = tuple(field.name for field in Order._meta.fields)
    inlines = (OrderItemInline,)
    fieldsets = (
        ("Order", {"fields": (
            "reference", "user", "status", "created_at", "updated_at",
            "paid_at", "stock_reserved",
        )}),
        ("Customer and delivery", {"fields": (
            "full_name", "email", "phone", "address_line1", "address_line2",
            "town_or_city", "county", "postal_code", "country",
        )}),
        ("Saved totals", {"fields": ("currency", "delivery_cost", "total")}),
        ("Payment identifiers", {"fields": (
            "stripe_checkout_session_id", "stripe_payment_intent_id",
            "checkout_token",
        )}),
        ("Saved Stripe request", {
            "fields": ("stripe_checkout_request",), "classes": ("collapse",),
        }),
    )
