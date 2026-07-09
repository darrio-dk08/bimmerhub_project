from django.db import models
from django.contrib.auth.models import User


class Vehicle(models.Model):
    """
    Stores vehicles belonging to users.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="vehicles"
    )

    make = models.CharField(
        max_length=50,
        default="BMW"
    )

    model = models.CharField(max_length=100)

    year = models.PositiveIntegerField()

    engine = models.CharField(max_length=100)

    registration = models.CharField(
        max_length=20,
        blank=True
    )

    def __str__(self):
        return f"{self.year} {self.make} {self.model}"