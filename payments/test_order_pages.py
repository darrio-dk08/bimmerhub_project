from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from parts.models import Category, Part

from .models import Order, OrderItem


class CustomerOrderPageTests(TestCase):
    """Order history must be private and use immutable saved prices."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="history_user",
        )
        cls.other = get_user_model().objects.create_user(
            username="history_other",
        )
        category = Category.objects.create(name="Filters")
        cls.part = Part.objects.create(
            category=category, name="Original filter", part_number="HISTORY-1",
            compatible_model="F10", price=Decimal("24.99"), stock=5,
        )
        cls.order = cls.make_order(cls.user)
        cls.other_order = cls.make_order(cls.other)
        cls.item = OrderItem.objects.create(
            order=cls.order, part=cls.part, product_name="Original filter",
            part_number="HISTORY-1", unit_price=Decimal("24.99"), quantity=2,
        )

    @staticmethod
    def make_order(user, **kwargs):
        return Order.objects.create(
            user=user, full_name="History Customer",
            email="history@example.com", phone="0871234567",
            address_line1="1 Saved Street", town_or_city="Donegal",
            country="IE", total=Decimal("79.98"),
            delivery_cost=Decimal("30.00"), **kwargs,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.list_url = reverse("payments:order_list")
        self.detail_url = reverse(
            "payments:order_detail", args=[self.order.reference],
        )

    def test_anonymous_visitors_must_log_in(self):
        self.client.logout()
        for url in (self.list_url, self.detail_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(
                    reverse("account_login")))

    def test_list_contains_only_owned_orders(self):
        response = self.client.get(self.list_url, {"user": self.other.pk})
        self.assertContains(response, str(self.order.reference))
        self.assertNotContains(response, str(self.other_order.reference))
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_other_customer_order_is_404_even_for_staff(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse(
            "payments:order_detail", args=[self.other_order.reference],
        ))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "1 Saved Street", status_code=404)

    def test_unknown_and_malformed_references_are_404(self):
        for reference in (str(uuid4()), "not-a-uuid"):
            response = self.client.get(f"/basket/orders/{reference}/")
            self.assertEqual(response.status_code, 404)

    def test_orders_without_customer_are_not_visible(self):
        orphan = self.make_order(None)
        self.assertNotContains(self.client.get(
            self.list_url), str(orphan.reference))
        response = self.client.get(reverse(
            "payments:order_detail", args=[orphan.reference],
        ))
        self.assertEqual(response.status_code, 404)

    def test_history_is_newest_first_and_paginated(self):
        newer = [self.make_order(self.user) for _ in range(20)]
        response = self.client.get(self.list_url)
        page = response.context["page_obj"]
        self.assertEqual(len(page.object_list), 20)
        self.assertEqual(page.object_list[0].pk, newer[-1].pk)
        self.assertContains(response, "Page 1 of 2")
        second = self.client.get(self.list_url, {"page": 2})
        self.assertEqual(list(second.context["page_obj"]), [self.order])
        self.assertContains(second, "Previous")

    def test_invalid_page_numbers_have_safe_fallback(self):
        for value in ("bad", "-1", "99999"):
            with self.subTest(page=value):
                response = self.client.get(self.list_url, {"page": value})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, str(self.order.reference))

    def test_empty_history_has_catalogue_link(self):
        self.order.delete()
        response = self.client.get(self.list_url)
        self.assertContains(response, "No orders yet")
        self.assertContains(response, reverse("parts:part_list"))
        self.assertNotContains(response, str(self.other_order.reference))

    def test_detail_uses_saved_values_after_catalogue_changes(self):
        self.part.name = "Different catalogue name"
        self.part.price = Decimal("999.00")
        self.part.save()
        response = self.client.get(self.detail_url)
        for text in ("Original filter", "HISTORY-1", "24.99", "49.98",
                     "30.00", "79.98", "1 Saved Street", "Ireland"):
            self.assertContains(response, text)
        self.assertNotContains(response, "Different catalogue name")
        self.assertNotContains(response, "999.00")

    def test_deleted_product_does_not_break_detail(self):
        self.part.delete()
        response = self.client.get(self.detail_url)
        self.assertContains(response, "Original filter")
        self.assertContains(response, "79.98")

    def test_pending_paid_and_cancelled_display_correct_controls(self):
        manage_url = reverse("payments:payment_success",
                             args=[self.order.reference])
        for status, label in ((Order.Status.PENDING, "Awaiting payment"),
                              (Order.Status.PAID, "Paid"),
                              (Order.Status.CANCELLED, "Cancelled")):
            with self.subTest(status=status):
                Order.objects.filter(pk=self.order.pk).update(
                    status=status,
                    paid_at=(
                        timezone.now() if status == Order.Status.PAID else None
                    ),
                )
                response = self.client.get(self.detail_url)
                self.assertContains(response, label)
                if status == Order.Status.PENDING:
                    self.assertContains(response, manage_url)
                else:
                    self.assertNotContains(response, manage_url)

    def test_browsing_does_not_call_stripe_or_change_order_or_basket(self):
        session = self.client.session
        session["basket"] = {str(self.part.pk): 1}
        session.save()
        before = Order.objects.values().get(pk=self.order.pk)
        with patch("stripe.StripeClient") as client:
            self.client.get(self.list_url)
            self.client.get(self.detail_url)
        client.assert_not_called()
        self.assertEqual(before, Order.objects.values().get(pk=self.order.pk))
        self.assertEqual(self.client.session["basket"], {str(self.part.pk): 1})

    def test_pages_are_read_only_and_not_cacheable(self):
        for url in (self.list_url, self.detail_url):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 405)
                response = self.client.get(url)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertIn("private", response["Cache-Control"])

    def test_saved_customer_and_product_text_are_escaped(self):
        Order.objects.filter(pk=self.order.pk).update(
            full_name="<script>bad()</script>")
        OrderItem.objects.filter(pk=self.item.pk).update(
            product_name="<b>Saved</b>")
        response = self.client.get(self.detail_url)
        self.assertContains(response, "&lt;script&gt;bad()&lt;/script&gt;")
        self.assertContains(response, "&lt;b&gt;Saved&lt;/b&gt;")
        self.assertNotContains(response, "<script>bad()</script>")

    def test_navigation_link_is_only_shown_to_signed_in_users(self):
        self.assertContains(self.client.get(
            reverse("core:home")), self.list_url)
        self.client.logout()
        self.assertNotContains(self.client.get(
            reverse("core:home")), self.list_url)

    def test_payment_status_links_to_saved_order_details(self):
        Order.objects.filter(pk=self.order.pk).update(
            status=Order.Status.PAID, paid_at=timezone.now(),
        )
        response = self.client.get(reverse(
            "payments:payment_success", args=[self.order.reference],
        ))
        self.assertContains(response, self.detail_url)
