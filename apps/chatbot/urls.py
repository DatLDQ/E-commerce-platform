from django.urls import path

from . import views

app_name = "chatbot"
urlpatterns = [path("tin-nhan/", views.message, name="message")]
