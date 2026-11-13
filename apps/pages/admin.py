from django.contrib import admin

from .models import Banner, ContactMessage, NewsletterSubscriber

admin.site.site_header = "LevelUp Gear — Quản trị"
admin.site.site_title = "LevelUp Gear Admin"


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("title", "kicker", "theme", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")


@admin.register(ContactMessage)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("subject", "name", "email", "is_handled", "created_at")
    list_editable = ("is_handled",)


admin.site.register(NewsletterSubscriber)
