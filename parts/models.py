from django.db import models


class Category(models.Model):
    """
    Stores BMW part categories.
    """

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class Part(models.Model):
    """
    Stores BMW car parts.
    """

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="parts"
    )

    name = models.CharField(max_length=200)

    description = models.TextField()

    part_number = models.CharField(max_length=50, unique=True, default="TEMP-PART")

    compatible_model = models.CharField(
        max_length=100,
        help_text="Example: BMW F10 520d"
    )

    price = models.DecimalField(
        max_digits=8,
        decimal_places=2
    )

    stock = models.PositiveIntegerField(default=0)

    image = models.ImageField(
        upload_to="parts/",
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name