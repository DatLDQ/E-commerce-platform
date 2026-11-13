from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Address, User


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "phone", "is_staff", "date_joined")
    search_fields = ("username", "email", "phone", "first_name", "last_name")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Hồ sơ khách hàng", {"fields": ("phone", "gamer_tag", "favorite_genre", "marketing_opt_in", "data_consent_at")}),
    )
    inlines = [AddressInline]
