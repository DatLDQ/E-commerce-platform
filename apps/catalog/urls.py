from django.urls import path

from . import views

app_name = "catalog"
urlpatterns = [
    path("", views.product_list, name="list"),
    path("tim-kiem/goi-y/", views.autocomplete, name="autocomplete"),
    path("so-sanh/", views.compare, name="compare"),
    path("yeu-thich/", views.wishlist, name="wishlist"),
    path("yeu-thich/<int:product_id>/", views.toggle_wishlist, name="toggle_wishlist"),
    path("danh-muc/<slug:category_slug>/", views.product_list, name="category"),
    path("<slug:slug>/", views.product_detail, name="detail"),
    path("<slug:slug>/danh-gia/", views.add_review, name="review"),
]
