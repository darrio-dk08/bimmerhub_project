from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from parts.models import Category, Part

from .basket import BASKET_SESSION_KEY
from .models import Order, OrderItem


@override_settings(DELIVERY_CHARGE="30.00")
class CheckoutViewTests(TestCase):
    """Check checkout access, validation and order review."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="checkout_customer",
            email="customer@example.com",
            first_name="Test",
            last_name="Customer",
        )

        category = Category.objects.create(name="Filters")
        cls.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter.",
            part_number="CHECKOUT-FILTER-001",
            compatible_model="BMW F10 518d",
            price=Decimal("24.99"),
            stock=5,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.checkout_url = reverse("payments:checkout")
        self.basket_url = reverse("payments:basket_detail")

        self.valid_data = {
            "full_name": "Test Customer",
            "email": "customer@example.com",
            "phone": "0871234567",
            "address_line1": "1 Test Street",
            "address_line2": "",
            "town_or_city": "Donegal",
            "county": "",
            "postal_code": "",
            "country": "IE",
        }

        self.set_basket({str(self.part.pk): 2})

    def set_basket(self, contents):
        session = self.client.session
        session[BASKET_SESSION_KEY] = contents
        session.save()

    def test_login_required_for_get_and_post(self):
        self.client.logout()

        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.checkout_url,
                )

                self.assertEqual(response.status_code, 302)
                destination = urlsplit(response.url)

                self.assertEqual(
                    destination.path,
                    reverse("account_login"),
                )
                self.assertEqual(
                    parse_qs(destination.query).get("next"),
                    [self.checkout_url],
                )

    def test_checkout_displays_totals_and_initial_details(self):
        response = self.client.get(self.checkout_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "payments/checkout.html")
        self.assertEqual(response.context["total"], Decimal("49.98"))
        self.assertEqual(
            response.context["delivery_cost"],
            Decimal("30.00"),
        )
        self.assertEqual(
            response.context["grand_total"],
            Decimal("79.98"),
        )
        self.assertEqual(
            response.context["form"].initial["full_name"],
            "Test Customer",
        )
        self.assertEqual(
            response.context["form"].initial["email"],
            "customer@example.com",
        )
        self.assertContains(response, self.part.name)
        self.assertContains(response, "79.98")

    def test_empty_basket_redirects(self):
        self.set_basket({})

        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.checkout_url,
                )
                self.assertRedirects(response, self.basket_url)

        self.assertEqual(Order.objects.count(), 0)

    def test_insufficient_stock_blocks_get_and_post(self):
        self.part.stock = 1
        self.part.save(update_fields=["stock"])

        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.checkout_url,
                    self.valid_data,
                )
                self.assertRedirects(response, self.basket_url)

        self.assertEqual(Order.objects.count(), 0)

    def test_deleted_product_is_removed_and_requires_basket_review(self):
        deleted_part = Part.objects.create(
            category=self.part.category,
            name="Deleted product",
            description="Product removed from the catalogue.",
            part_number="CHECKOUT-DELETED-001",
            compatible_model="BMW F10",
            price=Decimal("10.00"),
            stock=3,
        )
        deleted_key = str(deleted_part.pk)

        self.set_basket({
            str(self.part.pk): 2,
            deleted_key: 1,
        })
        deleted_part.delete()

        response = self.client.post(
            self.checkout_url,
            self.valid_data,
        )

        self.assertRedirects(response, self.basket_url)
        self.assertEqual(
            self.client.session[BASKET_SESSION_KEY],
            {str(self.part.pk): 2},
        )
        self.assertEqual(Order.objects.count(), 0)

    def test_basket_is_cleared_when_all_products_are_deleted(self):
        self.part.delete()

        response = self.client.get(self.checkout_url)

        self.assertRedirects(response, self.basket_url)
        self.assertEqual(
            self.client.session[BASKET_SESSION_KEY],
            {},
        )

    def test_invalid_details_redisplay_form_with_errors(self):
        invalid_values = (
            {"email": "not-an-email"},
            {"country": "GB"},
            {"address_line1": ""},
        )

        for values in invalid_values:
            with self.subTest(values=values):
                response = self.client.post(
                    self.checkout_url,
                    {**self.valid_data, **values},
                )

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(
                    response,
                    "payments/checkout.html",
                )
                for field in values:
                    self.assertIn(
                        field,
                        response.context["form"].errors,
                    )

        self.assertEqual(Order.objects.count(), 0)

    def test_valid_review_ignores_submitted_prices_and_creates_no_order(self):
        data = {
            **self.valid_data,
            "total": "0.01",
            "delivery_cost": "0.00",
            "status": "paid",
        }

        response = self.client.post(self.checkout_url, data)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "payments/checkout_review.html",
        )
        self.assertEqual(
            response.context["grand_total"],
            Decimal("79.98"),
        )
        self.assertEqual(
            response.context["delivery_details"]["country"],
            "IE",
        )
        self.assertContains(response, "1 Test Street")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)

        self.part.refresh_from_db()
        self.assertEqual(self.part.stock, 5)
        self.assertEqual(
            self.client.session[BASKET_SESSION_KEY],
            {str(self.part.pk): 2},
        )

    def test_review_uses_current_database_price(self):
        self.part.price = Decimal("30.00")
        self.part.save(update_fields=["price"])

        response = self.client.post(
            self.checkout_url,
            self.valid_data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], Decimal("60.00"))
        self.assertEqual(
            response.context["grand_total"],
            Decimal("90.00"),
        )

    def test_checkout_post_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            self.checkout_url,
            self.valid_data,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Order.objects.count(), 0)
