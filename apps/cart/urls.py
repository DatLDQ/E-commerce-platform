from django.urls import path

from . import views

app_name = "cart"
urlpatterns = [
    path("", views.cart_detail, name="detail"),
    path("them/<int:product_id>/", views.add, name="add"),
    path("cap-nhat/<int:product_id>/", views.update, name="update"),
    path("xoa/<int:product_id>/", views.remove, name="remove"),
    path("ma-giam-gia/", views.apply_coupon, name="coupon"),
]
