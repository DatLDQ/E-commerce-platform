from django.urls import path

from . import views

app_name = "pages"
urlpatterns = [
    path("", views.home, name="home"),
    path("gioi-thieu/", views.about, name="about"),
    path("nguon-anh/", views.photo_credits, name="credits"),
    path("lien-he/", views.contact, name="contact"),
    path("hoi-dap/", views.faq, name="faq"),
    path("nhan-tin/", views.newsletter, name="newsletter"),
    path("chinh-sach/<slug:slug>/", views.policy, name="policy"),
]
