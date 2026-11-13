from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.orders.services import PROVINCES, normalize_province

from .models import Address, User


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(label="Tên", max_length=150)
    last_name = forms.CharField(label="Họ", max_length=150)
    email = forms.EmailField(label="Email")
    data_consent = forms.BooleanField(
        label="Tôi đồng ý cho LevelUp Gear thu thập và xử lý dữ liệu cá nhân theo Chính sách bảo mật (Luật Bảo vệ dữ liệu cá nhân 2025)",
        error_messages={"required": "Bạn cần đồng ý với chính sách xử lý dữ liệu cá nhân để tạo tài khoản."},
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "phone", "gamer_tag", "favorite_genre", "marketing_opt_in")
        labels = {"username": "Tên đăng nhập", "phone": "Số điện thoại", "marketing_opt_in": "Nhận email ưu đãi (có thể huỷ bất kỳ lúc nào)"}

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email này đã được sử dụng.")
        return email


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Tên đăng nhập hoặc email", max_length=254)


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone", "gamer_tag", "favorite_genre", "marketing_opt_in")
        labels = {"first_name": "Tên", "last_name": "Họ", "marketing_opt_in": "Nhận email ưu đãi"}

    def clean_email(self):
        # The DB unique constraint is case-sensitive on some backends; check case-insensitively
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Email này đã được tài khoản khác sử dụng.")
        return email


class AddressForm(forms.ModelForm):
    province = forms.ChoiceField(label="Tỉnh/thành", choices=[(p, p) for p in PROVINCES])

    class Meta:
        model = Address
        fields = ("full_name", "phone", "province", "ward", "street", "is_default")
        labels = {"ward": "Phường / Xã / Đặc khu"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["province"] = normalize_province(self.instance.province)
