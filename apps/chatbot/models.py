from django.conf import settings
from django.db import models


class ChatMessage(models.Model):
    """Chat transcript — lets staff review questions the bot could not answer."""

    session_key = models.CharField(max_length=40, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    role = models.CharField(max_length=10, choices=[("user", "Khách"), ("bot", "Bot")])
    text = models.TextField(max_length=2000)
    intent = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class FAQ(models.Model):
    """Editable knowledge base for the chatbot (managed in the admin)."""

    question = models.CharField(max_length=200)
    keywords = models.CharField(max_length=300, help_text="Từ khoá, ngăn cách dấu phẩy (không dấu cũng được)")
    answer = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "FAQ chatbot"
        verbose_name_plural = "FAQ chatbot"

    def __str__(self):
        return self.question
