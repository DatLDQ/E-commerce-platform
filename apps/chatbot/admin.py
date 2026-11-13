from django.contrib import admin

from .models import FAQ, ChatMessage


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("question", "keywords", "is_active")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "session_key", "role", "intent", "text")
    list_filter = ("role", "intent")
