from django.urls import path

from . import views

app_name = "orders"
urlpatterns = [
    path("thanh-toan/", views.checkout, name="checkout"),
    path("thanh-toan/bao-gia/", views.checkout_quote, name="quote"),
    path("tra-cuu/", views.lookup, name="lookup"),
    path("cua-toi/", views.my_orders, name="mine"),
    path("<str:code>/", views.detail, name="detail"),
    path("<str:code>/thanh-cong/", views.success, name="success"),
    path("<str:code>/huy/", views.cancel, name="cancel"),
    path("<str:code>/mua-lai/", views.buy_again, name="buy_again"),
]
