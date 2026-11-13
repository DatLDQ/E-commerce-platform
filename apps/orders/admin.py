from django.contrib import admin

from .models import Coupon, DeliveryMethod, Order, OrderItem, OrderStatusHistory


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name", "sku", "unit_price", "quantity")


class HistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    readonly_fields = ("status", "note", "changed_by", "created_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("code", "full_name", "total", "status", "payment_method", "payment_status", "delivery_method", "created_at")
    list_filter = ("status", "payment_status", "payment_method", "delivery_method")
    search_fields = ("code", "full_name", "email", "phone")
    readonly_fields = ("code", "access_token", "subtotal", "shipping_fee", "discount", "total", "created_at", "ip_address")
    inlines = [OrderItemInline, HistoryInline]
    date_hierarchy = "created_at"


@admin.register(DeliveryMethod)
class DeliveryMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "base_fee", "min_days", "max_days", "is_pickup", "is_active")


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "kind", "value", "min_order", "used_count", "usage_limit", "valid_to", "is_active")
