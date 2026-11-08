from django.urls import path

from . import views, webhooks

app_name = "payments"

urlpatterns = [
    path("", views.basket_detail, name="basket_detail"),
    path("add/<int:pk>/", views.basket_add, name="basket_add"),
    path("update/<int:pk>/", views.basket_update, name="basket_update"),
    path("remove/<int:pk>/", views.basket_remove, name="basket_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("webhook/", webhooks.stripe_webhook, name="stripe_webhook"),
]