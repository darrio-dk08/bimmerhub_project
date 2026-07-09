from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User


class Vehicle(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    make = models.CharField(max_length=100, default="BMW")
    model = models.CharField(max_length=100)
    year = models.PositiveIntegerField()
    engine = models.CharField(max_length=100)
    registration = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.year} {self.make} {self.model}"