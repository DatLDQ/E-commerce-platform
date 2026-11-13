from django.urls import path

from . import views

app_name = "payments"
urlpatterns = [
    path("bat-dau/<str:code>/", views.start, name="start"),
    path("chuyen-khoan/<str:code>/", views.bank_transfer, name="bank_transfer"),
    path("chuyen-khoan/<str:code>/mo-phong-da-nhan/", views.bank_transfer_simulate, name="bank_transfer_simulate"),
    path("cong-thanh-toan-mo-phong/", views.mock_gateway, name="mock_gateway"),
    path("ket-qua/", views.payment_return, name="return"),
    path("ipn/", views.ipn, name="ipn"),
]
