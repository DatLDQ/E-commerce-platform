from django.apps import AppConfig


class CartConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cart"
    verbose_name = "Giỏ hàng"

    def ready(self):
        from . import services  # noqa: F401  (registers the login cart-merge signal)
