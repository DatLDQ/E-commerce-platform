from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models

phone_validator = RegexValidator(r"^(0|\+84)\d{9,10}$", "Số điện thoại Việt Nam không hợp lệ.")


class User(AbstractUser):
    """Customer / staff account.

    Consent fields record the data-subject's agreement as required by
    the Personal Data Protection Law 91/2025/QH15 (in force 1/1/2026) and Decree 356/2025/ND-CP.
    """

    email = models.EmailField("email", unique=True)
    phone = models.CharField("số điện thoại", max_length=15, blank=True, validators=[phone_validator])
    marketing_opt_in = models.BooleanField("nhận email khuyến mãi", default=False)
    data_consent_at = models.DateTimeField("đồng ý xử lý dữ liệu lúc", null=True, blank=True)
    gamer_tag = models.CharField("gamer tag", max_length=40, blank=True)
    favorite_genre = models.CharField(
        "thể loại game yêu thích",
        max_length=20,
        blank=True,
        choices=[
            ("fps", "FPS / Bắn súng"),
            ("moba", "MOBA"),
            ("rpg", "RPG / Nhập vai"),
            ("racing", "Đua xe / Mô phỏng"),
            ("casual", "Casual / Giải trí"),
        ],
    )

    def __str__(self):
        return self.get_full_name() or self.username


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    full_name = models.CharField("họ tên người nhận", max_length=120)
    phone = models.CharField("số điện thoại", max_length=15, validators=[phone_validator])
    province = models.CharField("tỉnh/thành", max_length=60)
    # Kept only for addresses entered before the 2025 reform (no district level now)
    district = models.CharField("quận/huyện (cũ)", max_length=60, blank=True)
    ward = models.CharField("phường/xã", max_length=60)
    street = models.CharField("địa chỉ", max_length=200)
    is_default = models.BooleanField("mặc định", default=False)

    class Meta:
        ordering = ["-is_default", "-id"]
        verbose_name = "địa chỉ"
        verbose_name_plural = "địa chỉ"

    def __str__(self):
        return f"{self.full_name} — {self.one_line()}"

    def one_line(self):
        parts = [self.street, self.ward, self.district, self.province]
        return ", ".join(p for p in parts if p)

    def save(self, *args, **kwargs):
        if self.is_default:
            Address.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
