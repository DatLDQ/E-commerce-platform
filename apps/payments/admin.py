from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("txn_ref", "order", "provider", "gateway", "amount", "status", "response_code", "created_at")
    list_filter = ("status", "provider", "gateway")
    search_fields = ("txn_ref", "order__code", "gateway_txn_no")
    readonly_fields = [f.name for f in Payment._meta.fields]
