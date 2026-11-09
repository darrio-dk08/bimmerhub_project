from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from parts.models import Category, Part

from .models import Order, OrderItem


class OrderAdminTests(TestCase):
    """Inspect orders without bypassing verified payment/stock transitions."""

    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.superuser = users.create_user(
            username="order_admin", is_staff=True, is_superuser=True,
        )
        cls.staff = users.create_user(username="order_viewer", is_staff=True)
        cls.customer = users.create_user(username="order_customer")
        category = Category.objects.create(name="Filters")
        cls.part = Part.objects.create(
            category=category, name="Catalogue filter", part_number="ADMIN-1",
            compatible_model="F10", price=Decimal("24.99"), stock=3,
        )
        cls.order = Order.objects.create(
            user=cls.customer, full_name="Saved Customer",
            email="saved@example.com", phone="0871234567",
            address_line1="1 Saved Street", town_or_city="Donegal",
            country="IE", delivery_cost=Decimal("30.00"),
            total=Decimal("79.98"), stock_reserved=True,
            stripe_checkout_session_id="cs_test_admin",
        )
        cls.item = OrderItem.objects.create(
            order=cls.order, part=cls.part, product_name="Saved filter",
            part_number="SAVED-1", unit_price=Decimal("24.99"), quantity=2,
        )

    def setUp(self):
        self.client.force_login(self.superuser)
        self.list_url = reverse("admin:payments_order_changelist")
        self.detail_url = reverse(
            "admin:payments_order_change", args=[self.order.pk],
        )

    def grant(self, *codes):
        self.staff.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="payments", codename__in=codes,
        ))
        self.client.force_login(self.staff)

    def test_superuser_can_inspect_order_and_saved_items(self):
        response = self.client.get(self.detail_url)
        for text in (
            "Saved Customer", "1 Saved Street", "Saved filter", "SAVED-1",
            "24.99", "49.98", "30.00", "79.98", "cs_test_admin",
        ):
            self.assertContains(response, text)
        for flag in (
            "has_add_permission", "has_change_permission",
            "has_delete_permission",
        ):
            self.assertFalse(response.context[flag])
        self.assertNotContains(response, 'name="_save"')
        self.assertNotContains(response, 'name="status"')
        self.assertNotContains(response, 'name="items-0-quantity"')

    def test_view_only_staff_can_see_order_and_inline(self):
        self.grant("view_order")
        self.assertContains(self.client.get(self.list_url), "Saved Customer")
        self.assertContains(self.client.get(self.detail_url), "Saved filter")

    def test_staff_without_order_permission_is_denied(self):
        self.client.force_login(self.staff)
        for url in (self.list_url, self.detail_url):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_customer_and_anonymous_are_redirected_to_admin_login(self):
        for user in (self.customer, None):
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url in (self.list_url, self.detail_url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(
                    reverse("admin:login"),
                ))

    def test_forged_changes_are_denied_even_for_superuser(self):
        before = Order.objects.values().get(pk=self.order.pk)
        item_before = OrderItem.objects.values().get(pk=self.item.pk)
        response = self.client.post(self.detail_url, {
            "status": "paid", "total": "0.00", "stock_reserved": "",
            "stripe_payment_intent_id": "pi_forged", "full_name": "Changed",
            "items-0-id": self.item.pk, "items-0-quantity": "999",
            "items-0-DELETE": "on", "_save": "Save",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Order.objects.values().get(pk=self.order.pk), before)
        self.assertEqual(
            OrderItem.objects.values().get(pk=self.item.pk), item_before,
        )
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 3)

    def test_add_and_delete_routes_are_denied_for_superuser(self):
        urls = (
            reverse("admin:payments_order_add"),
            reverse("admin:payments_order_delete", args=[self.order.pk]),
        )
        for url in urls:
            for method in (self.client.get, self.client.post):
                with self.subTest(url=url, method=method.__name__):
                    self.assertEqual(method(url).status_code, 403)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)

    def test_bulk_delete_action_cannot_delete_orders(self):
        response = self.client.get(self.list_url)
        self.assertIsNone(response.context["action_form"])
        self.client.post(self.list_url, {
            "action": "delete_selected", "_selected_action": [self.order.pk],
            "post": "yes",
        })
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())

    def test_change_permission_does_not_allow_mutations(self):
        self.grant("change_order", "add_order", "delete_order")
        self.assertContains(self.client.get(self.detail_url), "Saved filter")
        self.assertEqual(self.client.post(self.detail_url).status_code, 403)

    def test_search_and_status_filters(self):
        for query in (
            str(self.order.reference), "saved@example.com", "Saved Customer",
            "cs_test_admin",
        ):
            self.assertContains(self.client.get(self.list_url, {"q": query}),
                                str(self.order.reference))
        response = self.client.get(self.list_url, {"status__exact": "paid"})
        self.assertEqual(response.context["cl"].result_count, 0)
        response = self.client.get(self.list_url, {"q": "missing customer"})
        self.assertEqual(response.context["cl"].result_count, 0)

    def test_deleted_catalogue_product_preserves_admin_snapshots(self):
        self.part.delete()
        response = self.client.get(self.detail_url)
        self.assertContains(response, "Saved filter")
        self.assertContains(response, "24.99")

    def test_browsing_does_not_call_stripe_or_change_order(self):
        before = Order.objects.values().get(pk=self.order.pk)
        with patch("stripe.StripeClient") as client:
            self.client.get(self.list_url)
            self.client.get(self.detail_url)
        client.assert_not_called()
        self.assertEqual(Order.objects.values().get(pk=self.order.pk), before)

    def test_items_have_no_separate_editable_admin(self):
        self.assertNotIn(OrderItem, admin.site._registry)
