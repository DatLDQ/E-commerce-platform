import secrets

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product


class DeliveryMethod(models.Model):
    """Shipping option offered at checkout (standard / express / store pickup)."""

    code = models.SlugField(unique=True)
    name = models.CharField("tên", max_length=80)
    description = models.CharField("mô tả", max_length=200, blank=True)
    base_fee = models.PositiveIntegerField("phí cơ bản (VND)", default=30000)
    fee_per_extra_kg = models.PositiveIntegerField("phí mỗi kg vượt 2kg", default=5000)
    outer_region_surcharge = models.PositiveIntegerField("phụ phí ngoài TP.HCM", default=10000)
    min_days = models.PositiveSmallIntegerField("giao nhanh nhất (ngày)", default=2)
    max_days = models.PositiveSmallIntegerField("giao chậm nhất (ngày)", default=4)
    only_provinces = models.CharField(
        "chỉ áp dụng cho", max_length=200, blank=True, help_text="Danh sách tỉnh, ngăn cách dấu phẩy. Trống = toàn quốc"
    )
    free_ship_eligible = models.BooleanField("áp dụng miễn phí ship", default=True)
    is_pickup = models.BooleanField("nhận tại cửa hàng", default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]
        verbose_name = "phương thức giao hàng"
        verbose_name_plural = "phương thức giao hàng"

    def __str__(self):
        return self.name

    @property
    def province_list(self):
        return [p.strip() for p in self.only_provinces.split(",") if p.strip()]

    def available_for(self, province):
        return not self.province_list or province in self.province_list

    def eta_label(self):
        if self.is_pickup:
            return "Nhận trong 2 giờ sau khi xác nhận"
        if self.max_days == 0:
            return "Giao trong ngày"
        return f"{self.min_days}–{self.max_days} ngày"


class Coupon(models.Model):
    PERCENT, FIXED, FREESHIP = "percent", "fixed", "freeship"
    code = models.CharField("mã", max_length=30, unique=True)
    description = models.CharField("mô tả", max_length=200, blank=True)
    kind = models.CharField(
        "loại", max_length=10, choices=[(PERCENT, "Giảm %"), (FIXED, "Giảm tiền"), (FREESHIP, "Miễn phí vận chuyển")]
    )
    value = models.PositiveIntegerField("giá trị", default=0, help_text="% hoặc số tiền VND")
    max_discount = models.PositiveIntegerField("giảm tối đa (VND)", null=True, blank=True)
    min_order = models.PositiveIntegerField("đơn tối thiểu (VND)", default=0)
    usage_limit = models.PositiveIntegerField("số lượt tối đa", null=True, blank=True)
    used_count = models.PositiveIntegerField("đã dùng", default=0)
    first_order_only = models.BooleanField("chỉ cho đơn đầu tiên", default=False)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "mã giảm giá"
        verbose_name_plural = "mã giảm giá"

    def __str__(self):
        return self.code

    def validate(self, subtotal, user=None):
        """Return (ok, message)."""
        now = timezone.now()
        if not self.is_active or now < self.valid_from or (self.valid_to and now > self.valid_to):
            return False, "Mã giảm giá đã hết hạn hoặc chưa được kích hoạt."
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            return False, "Mã giảm giá đã hết lượt sử dụng."
        if subtotal < self.min_order:
            return False, f"Đơn hàng tối thiểu {self.min_order:,}₫ để dùng mã này.".replace(",", ".")
        if self.first_order_only:
            if not user or not user.is_authenticated:
                return False, "Vui lòng đăng nhập để dùng mã cho đơn đầu tiên."
            if user.orders.exclude(status=Order.Status.CANCELLED).exists():
                return False, "Mã chỉ áp dụng cho đơn hàng đầu tiên."
        return True, "Áp dụng mã thành công."

    def terms(self):
        """Short human-readable conditions, e.g. "giảm 10% (tối đa 200.000₫) cho đơn đầu tiên, cần đăng nhập"."""
        money = lambda v: f"{v:,}₫".replace(",", ".")  # noqa: E731
        if self.kind == self.PERCENT:
            parts = [f"giảm {self.value}%" + (f" (tối đa {money(self.max_discount)})" if self.max_discount else "")]
        elif self.kind == self.FIXED:
            parts = [f"giảm {money(self.value)}"]
        else:
            parts = ["miễn phí vận chuyển"]
        if self.min_order:
            parts.append(f"đơn từ {money(self.min_order)}")
        if self.first_order_only:
            parts.append("chỉ cho đơn đầu tiên của tài khoản đã đăng nhập")
        return ", ".join(parts)

    def discount_for(self, subtotal):
        if self.kind == self.PERCENT:
            d = subtotal * self.value // 100
            if self.max_discount:
                d = min(d, self.max_discount)
            return d
        if self.kind == self.FIXED:
            return min(self.value, subtotal)
        return 0


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Chờ xác nhận"
        CONFIRMED = "confirmed", "Đã xác nhận"
        PACKING = "packing", "Đang đóng gói"
        SHIPPING = "shipping", "Đang giao"
        DELIVERED = "delivered", "Đã giao"
        COMPLETED = "completed", "Hoàn tất"
        CANCELLED = "cancelled", "Đã huỷ"
        RETURNED = "returned", "Đã hoàn trả"

    class PaymentMethod(models.TextChoices):
        COD = "cod", "Thanh toán khi nhận hàng (COD)"
        VNPAY = "vnpay", "VNPay (ATM / Visa / QR)"
        MOMO = "momo", "Ví MoMo"
        BANK = "bank", "Chuyển khoản ngân hàng (VietQR)"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Chưa thanh toán"
        PAID = "paid", "Đã thanh toán"
        FAILED = "failed", "Thanh toán lỗi"
        REFUNDED = "refunded", "Đã hoàn tiền"

    # Allowed transitions — enforced in services.change_status()
    TRANSITIONS = {
        Status.PENDING: [Status.CONFIRMED, Status.CANCELLED],
        Status.CONFIRMED: [Status.PACKING, Status.CANCELLED],
        Status.PACKING: [Status.SHIPPING, Status.CANCELLED],
        Status.SHIPPING: [Status.DELIVERED, Status.RETURNED],
        Status.DELIVERED: [Status.COMPLETED, Status.RETURNED],
        Status.COMPLETED: [Status.RETURNED],
        Status.CANCELLED: [],
        Status.RETURNED: [],
    }

    code = models.CharField("mã đơn", max_length=20, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    access_token = models.CharField(max_length=32, editable=False, help_text="Cho khách vãng lai tra cứu đơn")
    # Customer & shipping snapshot (kept even if the address book changes)
    full_name = models.CharField("họ tên", max_length=120)
    email = models.EmailField()
    phone = models.CharField("điện thoại", max_length=15)
    province = models.CharField("tỉnh/thành", max_length=60)
    # Pre-reform field: since 1/7/2025 addresses are province -> ward/commune
    district = models.CharField("quận/huyện (cũ)", max_length=60, blank=True)
    ward = models.CharField("phường/xã", max_length=60, blank=True)
    street = models.CharField("địa chỉ", max_length=200)
    note = models.CharField("ghi chú", max_length=300, blank=True)
    want_vat_invoice = models.BooleanField("xuất hoá đơn VAT", default=False)
    vat_company = models.CharField("tên công ty", max_length=200, blank=True)
    vat_tax_code = models.CharField("MST", max_length=20, blank=True)
    # Delivery
    delivery_method = models.ForeignKey(DeliveryMethod, on_delete=models.PROTECT, verbose_name="giao hàng")
    tracking_number = models.CharField("mã vận đơn", max_length=40, blank=True)
    carrier = models.CharField("đơn vị vận chuyển", max_length=40, blank=True)
    # Money (all VND, integers)
    subtotal = models.PositiveIntegerField("tạm tính")
    shipping_fee = models.PositiveIntegerField("phí vận chuyển", default=0)
    discount = models.PositiveIntegerField("giảm giá", default=0)
    total = models.PositiveIntegerField("tổng cộng")
    coupon = models.ForeignKey(Coupon, null=True, blank=True, on_delete=models.SET_NULL)
    # Status
    status = models.CharField("trạng thái", max_length=12, choices=Status.choices, default=Status.PENDING)
    payment_method = models.CharField("thanh toán", max_length=8, choices=PaymentMethod.choices)
    payment_status = models.CharField(
        "trạng thái TT", max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "đơn hàng"
        verbose_name_plural = "đơn hàng"

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_code()
        if not self.access_token:
            self.access_token = secrets.token_hex(16)
        super().save(*args, **kwargs)

    @staticmethod
    def generate_code():
        while True:
            code = "LU" + timezone.localtime().strftime("%y%m%d") + secrets.token_hex(3).upper()
            if not Order.objects.filter(code=code).exists():
                return code

    def get_absolute_url(self):
        return reverse("orders:detail", args=[self.code]) + f"?t={self.access_token}"

    @property
    def address_line(self):
        return ", ".join(p for p in [self.street, self.ward, self.district, self.province] if p)

    @property
    def can_cancel(self):
        return self.status in (self.Status.PENDING, self.Status.CONFIRMED)

    @property
    def needs_online_payment(self):
        return self.payment_method != self.PaymentMethod.COD and self.payment_status != self.PaymentStatus.PAID

    @property
    def allowed_next_statuses(self):
        return [(s, self.Status(s).label) for s in self.TRANSITIONS.get(self.status, [])]

    @property
    def vat_amount(self):
        # Prices are VAT-inclusive: VAT = total * r / (1 + r)
        r = settings.VAT_RATE
        return round(self.total * r / (1 + r))

    @property
    def progress_steps(self):
        flow = [self.Status.PENDING, self.Status.CONFIRMED, self.Status.PACKING, self.Status.SHIPPING, self.Status.DELIVERED]
        try:
            idx = flow.index(self.status)
        except ValueError:
            idx = len(flow) if self.status == self.Status.COMPLETED else -1
        return [(s.label, i <= idx) for i, s in enumerate(flow)]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL, related_name="order_items")
    product_name = models.CharField(max_length=200)
    sku = models.CharField(max_length=40)
    # snapshot like name / SKU: revenue by category still adds up after a product is deleted
    category_name = models.CharField(max_length=100, blank=True)
    unit_price = models.PositiveIntegerField()
    unit_cost = models.PositiveIntegerField(default=0)
    quantity = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    status = models.CharField(max_length=12, choices=Order.Status.choices)
    note = models.CharField(max_length=300, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
