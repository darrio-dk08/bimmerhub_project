from django.urls import path

from . import payment_actions, payment_returns, views, webhooks

app_name = "payments"

urlpatterns = [
    path("", views.basket_detail, name="basket_detail"),
    path("add/<int:pk>/", views.basket_add, name="basket_add"),
    path("update/<int:pk>/", views.basket_update, name="basket_update"),
    path("remove/<int:pk>/", views.basket_remove, name="basket_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path(
        "payment/<uuid:reference>/success/",
        payment_returns.payment_success,
        name="payment_success",
    ),
    path(
        "payment/<uuid:reference>/cancel/",
        payment_returns.payment_cancel,
        name="payment_cancel",
    ),
    path("checkout/pay/", payment_actions.payment_start, name="payment_start"),
    path(
        "payment/<uuid:reference>/retry/",
        payment_actions.payment_retry,
        name="payment_retry",
    ),
    path(
        "payment/<uuid:reference>/cancel-confirm/",
        payment_actions.payment_cancel_confirm,
        name="payment_cancel_confirm",
    ),
    path("webhook/", webhooks.stripe_webhook, name="stripe_webhook"),
]
