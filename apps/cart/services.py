"""Cart operations. Carts are keyed by user (when logged in) or session."""
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.dispatch import receiver

from .models import Cart, CartItem

MAX_QTY_PER_LINE = 10


def _session_key(request, create):
    if not request.session.session_key and create:
        request.session.save()
    return request.session.session_key


def get_cart(request, create=False):
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart is None and create:
            cart = Cart.objects.create(user=request.user)
        return cart
    key = _session_key(request, create)
    if not key:
        return None
    cart = Cart.objects.filter(session_key=key, user__isnull=True).first()
    if cart is None:
        # session key rotates on some actions — fall back to the remembered cart id
        cid = request.session.get("guest_cart_id")
        if cid:
            cart = Cart.objects.filter(pk=cid, user__isnull=True).first()
            if cart:
                cart.session_key = key
                cart.save(update_fields=["session_key"])
    if cart is None and create:
        cart = Cart.objects.create(session_key=key)
    if cart is not None:
        request.session["guest_cart_id"] = cart.pk
    return cart


def max_quantity(product):
    """Most units of one product a single order may hold: stock, but never more than the per-line limit."""
    return max(0, min(product.stock, MAX_QTY_PER_LINE))


def cap_message(product, wanted):
    """Why `wanted` units were cut down, or None when they fit."""
    limit = max_quantity(product)
    if wanted <= limit or limit <= 0:
        return None
    if limit == MAX_QTY_PER_LINE and product.stock > MAX_QTY_PER_LINE:
        return f"Mỗi đơn mua tối đa {MAX_QTY_PER_LINE} sản phẩm “{product.name}” — số lượng đã được điều chỉnh về {limit}."
    return f"Chỉ còn {limit} sản phẩm “{product.name}” trong kho — số lượng đã được điều chỉnh về {limit}."


def add_item(cart, product, quantity=1):
    """Add quantity, capped by stock and per-line limit. Returns (item, message)."""
    item, _ = CartItem.objects.get_or_create(cart=cart, product=product, defaults={"quantity": 0})
    wanted = item.quantity + max(1, int(quantity))
    capped = min(wanted, max_quantity(product))
    msg = cap_message(product, wanted)
    if capped <= 0:
        item.delete()
        return None, f"“{product.name}” đã hết hàng."
    item.quantity = capped
    item.save()
    cart.save(update_fields=["updated_at"])
    return item, msg


def set_quantity(cart, product_id, quantity):
    """Set a line's quantity (0 removes it). Returns (item|None, message|None)."""
    item = cart.items.select_related("product").filter(product_id=product_id).first()
    if not item:
        return None, None
    quantity = int(quantity)
    if quantity <= 0:
        item.delete()
        return None, None
    item.quantity = min(quantity, max_quantity(item.product))
    if item.quantity <= 0:
        item.delete()
        return None, f"“{item.product.name}” đã hết hàng."
    item.save()
    return item, cap_message(item.product, quantity)


def remove_item(cart, product_id):
    cart.items.filter(product_id=product_id).delete()


@receiver(user_logged_in)
def merge_session_cart(sender, request, user, **kwargs):
    """When a guest logs in, move their session cart into their account cart.

    Django rotates the session key on login but keeps the data, so we look the
    guest cart up by the id stored in the session before login.
    """
    guest_cart_id = request.session.get("guest_cart_id")
    if not guest_cart_id:
        return
    guest = Cart.objects.filter(pk=guest_cart_id, user__isnull=True).first()
    if not guest:
        return
    with transaction.atomic():
        cart, _ = Cart.objects.get_or_create(user=user)
        for item in guest.items.select_related("product"):
            add_item(cart, item.product, item.quantity)
        if guest.coupon_code and not cart.coupon_code:
            cart.coupon_code = guest.coupon_code
            cart.save()
        guest.delete()
    request.session.pop("guest_cart_id", None)
