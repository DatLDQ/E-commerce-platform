from django.conf import settings
from django.db import models

from apps.catalog.models import Product


class ProductView(models.Model):
    """Browsing event — input signal for personalised recommendations and analytics."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="views")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class SearchLog(models.Model):
    """Search queries — used by the analytics dashboard (top searches / zero-result searches)."""

    query = models.CharField(max_length=200)
    results = models.PositiveIntegerField(default=0)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)


class SiteVisit(models.Model):
    """One row per (session, day) — denominator for the conversion-rate KPI."""

    session_key = models.CharField(max_length=40)
    day = models.DateField(db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=40, blank=True, help_text="utm_source / referrer")

    class Meta:
        unique_together = ("session_key", "day")
