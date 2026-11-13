from django.urls import path

from . import views

app_name = "dashboard"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("san-pham/", views.product_list, name="products"),
    path("san-pham/them/", views.product_edit, name="product_add"),
    path("san-pham/<int:pk>/", views.product_edit, name="product_edit"),
    path("san-pham/<int:pk>/an-hien/", views.product_toggle, name="product_toggle"),
    path("san-pham/<int:pk>/ton-kho/", views.product_stock, name="product_stock"),
    path("anh/<int:pk>/xoa/", views.product_image_delete, name="image_delete"),
    path("don-hang/", views.order_list, name="orders"),
    path("don-hang/<str:code>/", views.order_detail, name="order_detail"),
    path("don-hang/<str:code>/hoa-don/", views.invoice, name="invoice"),
    path("khach-hang/", views.customers, name="customers"),
    path("khach-hang/<int:pk>/", views.customer_detail, name="customer_detail"),
]
