from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Category, Part


class PartCatalogueTests(TestCase):
    """Check public catalogue access and product display."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Filters")

        cls.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter for a BMW F10.",
            part_number="TEST-FILTER-001",
            compatible_model="BMW F10 518d",
            price=Decimal("24.99"),
            stock=5,
        )

    def test_catalogue_url(self):
        self.assertEqual(reverse("parts:part_list"), "/parts/")

    def test_catalogue_is_public(self):
        response = self.client.get("/parts/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "parts/part_list.html")

    def test_catalogue_displays_product_information(self):
        response = self.client.get("/parts/")

        self.assertContains(response, self.part.name)
        self.assertContains(response, self.part.compatible_model)
        self.assertContains(response, "24.99")

    def test_product_without_image_has_placeholder(self):
        response = self.client.get("/parts/")

        self.assertContains(response, "No image available")

    def test_empty_catalogue_displays_helpful_message(self):
        Part.objects.all().delete()

        response = self.client.get("/parts/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No parts are available yet.")


class PartDetailTests(TestCase):
    """Check individual product pages and catalogue links."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Filters")

        cls.part = Part.objects.create(
            category=category,
            name="BMW F10 Oil Filter",
            description="Replacement oil filter for a BMW F10.",
            part_number="TEST-DETAIL-001",
            compatible_model="BMW F10 518d",
            price=Decimal("24.99"),
            stock=5,
        )

    def test_detail_url(self):
        url = reverse("parts:part_detail", args=[self.part.pk])

        self.assertEqual(url, f"/parts/{self.part.pk}/")

    def test_detail_page_is_public_and_displays_product(self):
        response = self.client.get(f"/parts/{self.part.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "parts/part_detail.html")
        self.assertContains(response, self.part.name)
        self.assertContains(response, self.part.description)
        self.assertContains(response, self.part.part_number)
        self.assertContains(response, self.part.compatible_model)
        self.assertContains(response, "24.99")
        self.assertContains(response, "In stock")

    def test_detail_without_image_displays_placeholder(self):
        response = self.client.get(f"/parts/{self.part.pk}/")

        self.assertContains(response, "No image available")

    def test_out_of_stock_product_remains_viewable(self):
        self.part.stock = 0
        self.part.save(update_fields=["stock"])

        response = self.client.get(f"/parts/{self.part.pk}/")

        self.assertContains(response, "Out of stock")

    def test_missing_product_returns_404(self):
        missing_pk = self.part.pk
        self.part.delete()

        response = self.client.get(f"/parts/{missing_pk}/")

        self.assertEqual(response.status_code, 404)

    def test_catalogue_links_to_product_detail(self):
        response = self.client.get("/parts/")
        detail_url = reverse("parts:part_detail", args=[self.part.pk])

        self.assertContains(response, f'href="{detail_url}"')
