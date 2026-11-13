from django.db import models

from apps.orders.models import Order


class Payment(models.Model):
    """One payment attempt for an order (an order can have several attempts)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Đang chờ"
        SUCCESS = "success", "Thành công"
        FAILED = "failed", "Thất bại"
        CANCELLED = "cancelled", "Khách huỷ"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    provider = models.CharField(max_length=10, choices=Order.PaymentMethod.choices)
    gateway = models.CharField(max_length=10, default="mock", help_text="mock | vnpay")
    txn_ref = models.CharField(max_length=40, unique=True)
    amount = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    gateway_txn_no = models.CharField(max_length=40, blank=True)
    response_code = models.CharField(max_length=10, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "giao dịch thanh toán"
        verbose_name_plural = "giao dịch thanh toán"

    def __str__(self):
        return f"{self.txn_ref} — {self.get_status_display()}"
