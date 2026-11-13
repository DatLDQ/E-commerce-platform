from django.db import models


class Banner(models.Model):
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=200, blank=True)
    cta_text = models.CharField(max_length=40, default="Mua ngay")
    cta_url = models.CharField(max_length=200, default="/san-pham/")
    theme = models.CharField(max_length=20, default="violet", choices=[("violet", "Violet"), ("lime", "Lime"), ("cyan", "Cyan")])
    kicker = models.CharField("nhãn nhỏ", max_length=40, blank=True, help_text="Dòng chữ nhỏ phía trên tiêu đề, vd. 'LevelUp Week'")
    image = models.ImageField(
        "ảnh nền", upload_to="banners/", blank=True,
        help_text="Ảnh ngang ≥ 1600px. Bỏ trống để dùng ảnh mặc định theo theme.",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self):
        return self.title


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField(max_length=3000)
    is_handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.subject


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class StoredFile(models.Model):
    """An uploaded file kept in the database (see apps.pages.storage.DatabaseStorage).

    Used on hosts whose disk is wiped on every deploy, so admin uploads survive restarts.
    """

    name = models.CharField(max_length=255, unique=True)
    content = models.BinaryField()
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "tệp đã tải lên"
        verbose_name_plural = "tệp đã tải lên"

    def __str__(self):
        return self.name
