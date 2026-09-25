from django.urls import path

from . import views

app_name = "parts"

urlpatterns = [
    path("", views.part_list, name="part_list"),
]