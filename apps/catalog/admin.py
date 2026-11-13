from django.contrib import admin
from django.utils.html import format_html

from .models import Brand, Category, Product, ProductImage, Review


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "country")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("thumb", "name", "sku", "category", "brand", "price", "sale_price", "stock", "is_active", "is_featured")
    list_display_links = ("thumb", "name")
    list_filter = ("is_active", "is_featured", "category", "brand")
    list_editable = ("price", "sale_price", "stock", "is_active", "is_featured")
    search_fields = ("name", "sku", "tags")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductImageInline]
    actions = ["activate", "deactivate"]

    @admin.display(description="")
    def thumb(self, obj):
        img = obj.main_image
        return format_html('<img src="{}" style="width:40px;height:40px;object-fit:cover;border-radius:6px">', img.image.url) if img else "—"

    @admin.action(description="Bật bán")
    def activate(self, request, qs):
        qs.update(is_active=True)

    @admin.action(description="Ngừng bán")
    def deactivate(self, request, qs):
        qs.update(is_active=False)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "rating", "is_verified_purchase", "is_approved", "created_at")
    list_filter = ("rating", "is_approved", "is_verified_purchase")
    list_editable = ("is_approved",)
