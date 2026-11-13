from django.conf import settings
from django.db import models

from apps.catalog.models import Product


class Cart(models.Model):
    """A cart belongs either to a logged-in user or to an anonymous session.

    Prices are never stored in the cart: they are always recomputed from the
    product at read time so a tampered request cannot change what is charged.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="cart")
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    coupon_code = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart #{self.pk} ({self.user or self.session_key})"

    @property
    def lines(self):
        return self.items.select_related("product", "product__brand").prefetch_related("product__images")

    @property
    def total_quantity(self):
        return sum(i.quantity for i in self.items.all())

    @property
    def subtotal(self):
        return sum(i.line_total for i in self.lines)


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("cart", "product")
        ordering = ["added_at"]

    @property
    def unit_price(self):
        return self.product.current_price

    @property
    def line_total(self):
        return self.unit_price * self.quantity
