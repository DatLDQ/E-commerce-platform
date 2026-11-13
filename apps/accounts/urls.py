from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"
urlpatterns = [
    path("dang-ky/", views.register, name="register"),
    path("dang-nhap/", views.RateLimitedLoginView.as_view(), name="login"),
    path("dang-xuat/", views.logout_view, name="logout"),
    path("ho-so/", views.profile, name="profile"),
    path("dia-chi/", views.addresses, name="addresses"),
    path("dia-chi/<int:pk>/sua/", views.address_edit, name="address_edit"),
    path("dia-chi/<int:pk>/xoa/", views.address_delete, name="address_delete"),
    path("dia-chi/<int:pk>/mac-dinh/", views.address_default, name="address_default"),
    path("quyen-rieng-tu/", views.privacy, name="privacy"),
    path("quyen-rieng-tu/tai-du-lieu/", views.export_data, name="export_data"),
    path("quyen-rieng-tu/xoa-tai-khoan/", views.delete_account, name="delete_account"),
    path(
        "doi-mat-khau/",
        auth_views.PasswordChangeView.as_view(template_name="accounts/form_page.html", success_url=reverse_lazy("accounts:profile"), extra_context={"title": "Đổi mật khẩu"}),
        name="password_change",
    ),
    path(
        "quen-mat-khau/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/form_page.html",
            email_template_name="emails/password_reset.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
            extra_context={"title": "Quên mật khẩu"},
        ),
        name="password_reset",
    ),
    path("quen-mat-khau/da-gui/", auth_views.PasswordResetDoneView.as_view(template_name="accounts/message.html", extra_context={"title": "Đã gửi email", "text": "Nếu email tồn tại trong hệ thống, bạn sẽ nhận được liên kết đặt lại mật khẩu."}), name="password_reset_done"),
    path(
        "dat-lai/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(template_name="accounts/form_page.html", success_url=reverse_lazy("accounts:login"), extra_context={"title": "Đặt mật khẩu mới"}),
        name="password_reset_confirm",
    ),
]
