from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count
from django.urls import reverse
from django.utils.text import slugify

from .utils import strip_accents


def unique_slug(instance, value, field="slug"):
    # strip_accents first: slugify() alone drops "đ" ("Đen" -> "en")
    base = slugify(strip_accents(value)) or "item"
    slug, i = base, 2
    Model = type(instance)
    while Model.objects.filter(**{field: slug}).exclude(pk=instance.pk).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


class Category(models.Model):
    name = models.CharField("tên", max_length=80)
    slug = models.SlugField(unique=True, blank=True)
    icon = models.CharField("icon", max_length=20, default="box", help_text="Tên icon trong sprite SVG")
    description = models.TextField("mô tả", blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "danh mục"
        verbose_name_plural = "danh mục"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:category", args=[self.slug])


class Brand(models.Model):
    name = models.CharField("thương hiệu", max_length=80, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    country = models.CharField("xuất xứ", max_length=60, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "thương hiệu"
        verbose_name_plural = "thương hiệu"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_ratings(self):
        return self.annotate(
            avg_rating=Avg("reviews__rating", filter=models.Q(reviews__is_approved=True)),
            review_count=Count("reviews", filter=models.Q(reviews__is_approved=True), distinct=True),
        )


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products", verbose_name="danh mục")
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products", verbose_name="thương hiệu")
    name = models.CharField("tên sản phẩm", max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    sku = models.CharField("mã SKU", max_length=40, unique=True)
    short_description = models.CharField("mô tả ngắn", max_length=300, blank=True)
    description = models.TextField("mô tả chi tiết", blank=True)
    specs = models.JSONField("thông số kỹ thuật", default=dict, blank=True)
    tags = models.CharField("tags", max_length=300, blank=True, help_text="Ngăn cách bởi dấu phẩy: rgb, wireless, fps…")
    price = models.PositiveIntegerField("giá niêm yết (VND)")
    sale_price = models.PositiveIntegerField("giá khuyến mãi (VND)", null=True, blank=True)
    cost_price = models.PositiveIntegerField("giá vốn (VND)", default=0, help_text="Dùng cho báo cáo lợi nhuận")
    stock = models.PositiveIntegerField("tồn kho", default=0)
    warranty_months = models.PositiveSmallIntegerField("bảo hành (tháng)", default=12)
    weight_grams = models.PositiveIntegerField("khối lượng (g)", default=500)
    is_active = models.BooleanField("đang bán", default=True)
    is_featured = models.BooleanField("nổi bật", default=False)
    search_text = models.TextField(blank=True, editable=False, help_text="Chuỗi không dấu để tìm kiếm")
    view_count = models.PositiveIntegerField(default=0, editable=False)
    sold_count = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "sản phẩm"
        verbose_name_plural = "sản phẩm"
        indexes = [models.Index(fields=["is_active", "category"]), models.Index(fields=["price"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        if self.sale_price and self.sale_price >= self.price:
            self.sale_price = None
        from .utils import strip_accents

        self.search_text = strip_accents(
            " ".join([self.name, self.sku, self.tags, self.short_description, str(self.brand), str(self.category)])
        )
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:detail", args=[self.slug])

    @property
    def current_price(self):
        return self.sale_price or self.price

    @property
    def discount_percent(self):
        if self.sale_price:
            return round(100 * (self.price - self.sale_price) / self.price)
        return 0

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def low_stock(self):
        return 0 < self.stock <= settings.LOW_STOCK_THRESHOLD

    @property
    def main_image(self):
        imgs = getattr(self, "_prefetched_objects_cache", {}).get("images")
        if imgs is not None:
            return imgs[0] if imgs else None
        return self.images.first()

    @property
    def tag_list(self):
        return [t.strip().lower() for t in self.tags.split(",") if t.strip()]


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/%Y/%m/")
    alt = models.CharField("alt text", max_length=200, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "ảnh sản phẩm"
        verbose_name_plural = "ảnh sản phẩm"

    def __str__(self):
        return self.alt or self.product.name


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120, blank=True)
    comment = models.TextField(max_length=2000)
    is_verified_purchase = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("product", "user")
        verbose_name = "đánh giá"
        verbose_name_plural = "đánh giá"

    def __str__(self):
        return f"{self.product} — {self.rating}★"


class Wishlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "product")
