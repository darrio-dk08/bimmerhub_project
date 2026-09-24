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