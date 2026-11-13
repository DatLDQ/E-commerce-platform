"""Order domain logic: price quotes, shipping fees, placing orders, status workflow.

All money is computed server-side from the database — nothing price-related is
trusted from the browser.
"""
import logging
import math

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone

from apps.catalog.models import Product

from .models import Coupon, DeliveryMethod, Order, OrderItem, OrderStatusHistory

log = logging.getLogger("apps.orders")

INNER_REGION = {"TP. Hồ Chí Minh"}

# 34 provincial-level units after the 2025 administrative reform (Resolution
# 202/2025/QH15, effective 1/7/2025). Local government is now two-level:
# province -> ward/commune, so addresses no longer have a district.
PROVINCES = [
    "TP. Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Hải Phòng", "Cần Thơ", "Huế",
    "An Giang", "Bắc Ninh", "Cà Mau", "Cao Bằng", "Đắk Lắk", "Điện Biên", "Đồng Nai", "Đồng Tháp",
    "Gia Lai", "Hà Tĩnh", "Hưng Yên", "Khánh Hòa", "Lai Châu", "Lâm Đồng", "Lạng Sơn", "Lào Cai",
    "Nghệ An", "Ninh Bình", "Phú Thọ", "Quảng Ngãi", "Quảng Ninh", "Quảng Trị", "Sơn La", "Tây Ninh",
    "Thái Nguyên", "Thanh Hóa", "Tuyên Quang", "Vĩnh Long",
]

# Pre-reform province name -> the unit it was merged into. Used to migrate old
# addresses/orders and to accept legacy values from saved address books.
LEGACY_PROVINCES = {
    "Bình Dương": "TP. Hồ Chí Minh", "Bà Rịa - Vũng Tàu": "TP. Hồ Chí Minh",
    "Hà Giang": "Tuyên Quang", "Yên Bái": "Lào Cai", "Bắc Kạn": "Thái Nguyên",
    "Vĩnh Phúc": "Phú Thọ", "Hoà Bình": "Phú Thọ", "Hòa Bình": "Phú Thọ", "Bắc Giang": "Bắc Ninh",
    "Thái Bình": "Hưng Yên", "Hải Dương": "Hải Phòng", "Hà Nam": "Ninh Bình", "Nam Định": "Ninh Bình",
    "Quảng Bình": "Quảng Trị", "Quảng Nam": "Đà Nẵng", "Kon Tum": "Quảng Ngãi", "Bình Định": "Gia Lai",
    "Ninh Thuận": "Khánh Hòa", "Khánh Hoà": "Khánh Hòa", "Đắk Nông": "Lâm Đồng", "Bình Thuận": "Lâm Đồng",
    "Phú Yên": "Đắk Lắk", "Bình Phước": "Đồng Nai", "Long An": "Tây Ninh", "Sóc Trăng": "Cần Thơ",
    "Hậu Giang": "Cần Thơ", "Bến Tre": "Vĩnh Long", "Trà Vinh": "Vĩnh Long", "Tiền Giang": "Đồng Tháp",
    "Bạc Liêu": "Cà Mau", "Kiên Giang": "An Giang", "Thừa Thiên Huế": "Huế", "Thanh Hoá": "Thanh Hóa",
}


def normalize_province(name):
    name = (name or "").strip()
    return LEGACY_PROVINCES.get(name, name)


class CheckoutError(Exception):
    pass


def shipping_fee(method: DeliveryMethod, province: str, subtotal: int, weight_grams: int, coupon=None) -> int:
    if method.is_pickup:
        return 0
    if coupon and coupon.kind == Coupon.FREESHIP:
        return 0
    if method.free_ship_eligible and subtotal >= settings.FREE_SHIPPING_THRESHOLD:
        return 0
    fee = method.base_fee
    extra_kg = max(0, math.ceil((weight_grams - 2000) / 1000))
    fee += extra_kg * method.fee_per_extra_kg
    if province and province not in INNER_REGION:
        fee += method.outer_region_surcharge
    return fee


def resolve_coupon(code, subtotal, user):
    """Return (coupon|None, message|None)."""
    if not code:
        return None, None
    coupon = Coupon.objects.filter(code__iexact=code.strip()).first()
    if not coupon:
        return None, "Mã giảm giá không tồn tại."
    ok, msg = coupon.validate(subtotal, user)
    return (coupon if ok else None), msg


def drop_invalid_coupon(cart, user):
    """Remove a saved coupon the cart no longer qualifies for. Returns the reason, or None if nothing changed.

    Without this the code stays on the cart, hidden from the summary, and checkout keeps refusing the order.
    """
    if not cart or not cart.coupon_code:
        return None
    coupon, msg = resolve_coupon(cart.coupon_code, cart.subtotal, user)
    if coupon:
        return None
    code, cart.coupon_code = cart.coupon_code, ""
    cart.save(update_fields=["coupon_code"])
    return f"Đã gỡ mã {code}: {msg or 'mã không còn hiệu lực.'}"


def quote(cart, method=None, province="", user=None):
    """Full price breakdown for a cart. Used by cart page, checkout and order creation."""
    lines = list(cart.lines) if cart else []
    subtotal = sum(l.line_total for l in lines)
    weight = sum(l.product.weight_grams * l.quantity for l in lines)
    coupon, coupon_msg = resolve_coupon(cart.coupon_code if cart else "", subtotal, user)
    discount = coupon.discount_for(subtotal) if coupon else 0
    ship = shipping_fee(method, province, subtotal, weight, coupon) if method else 0
    total = max(0, subtotal - discount + ship)
    return {
        "lines": lines,
        "item_count": sum(l.quantity for l in lines),  # units, as in the header cart badge
        "subtotal": subtotal,
        "weight": weight,
        "coupon": coupon,
        "coupon_msg": coupon_msg,
        "discount": discount,
        "shipping_fee": ship,
        "total": total,
        "free_ship_gap": max(0, settings.FREE_SHIPPING_THRESHOLD - subtotal),
    }


def available_methods(province):
    return [m for m in DeliveryMethod.objects.filter(is_active=True) if m.available_for(province)]


@transaction.atomic
def place_order(*, cart, user, data, ip=None):
    """Create an order from a cart atomically.

    Rows of the purchased products are locked (SELECT … FOR UPDATE) so two
    customers cannot buy the last unit at the same time.
    """
    if not cart or not cart.items.exists():
        raise CheckoutError("Giỏ hàng trống.")
    method = data["delivery_method"]
    if not method.available_for(data["province"]):
        raise CheckoutError(f"{method.name} không hỗ trợ giao tới {data['province']}.")

    product_ids = list(cart.items.values_list("product_id", flat=True))
    locked = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=product_ids)}
    for item in cart.items.all():
        p = locked[item.product_id]
        if not p.is_active:
            raise CheckoutError(f"“{p.name}” đã ngừng kinh doanh, vui lòng xoá khỏi giỏ.")
        if p.stock < item.quantity:
            raise CheckoutError(f"“{p.name}” chỉ còn {p.stock} sản phẩm.")

    q = quote(cart, method, data["province"], user)
    if cart.coupon_code and not q["coupon"]:
        raise CheckoutError(q["coupon_msg"] or "Mã giảm giá không hợp lệ.")

    order = Order.objects.create(
        user=user if user and user.is_authenticated else None,
        full_name=data["full_name"],
        email=data["email"],
        phone=data["phone"],
        province=data["province"],
        district=data.get("district", ""),
        ward=data.get("ward", ""),
        street=data["street"],
        note=data.get("note", ""),
        want_vat_invoice=data.get("want_vat_invoice", False),
        vat_company=data.get("vat_company", ""),
        vat_tax_code=data.get("vat_tax_code", ""),
        delivery_method=method,
        subtotal=q["subtotal"],
        shipping_fee=q["shipping_fee"],
        discount=q["discount"],
        total=q["total"],
        coupon=q["coupon"],
        payment_method=data["payment_method"],
        ip_address=ip,
    )
    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                product=l.product,
                product_name=l.product.name,
                sku=l.product.sku,
                category_name=l.product.category.name,
                unit_price=l.unit_price,
                unit_cost=l.product.cost_price,
                quantity=l.quantity,
            )
            for l in q["lines"]
        ]
    )
    for l in q["lines"]:
        Product.objects.filter(pk=l.product_id).update(stock=F("stock") - l.quantity, sold_count=F("sold_count") + l.quantity)
    if q["coupon"]:
        Coupon.objects.filter(pk=q["coupon"].pk).update(used_count=F("used_count") + 1)
    OrderStatusHistory.objects.create(order=order, status=order.status, note="Khách đặt hàng", changed_by=order.user)

    cart.items.all().delete()
    cart.coupon_code = ""
    cart.save()
    transaction.on_commit(lambda: send_order_email(order, "Xác nhận đơn hàng"))
    log.info("Order %s placed: %s VND via %s", order.code, order.total, order.payment_method)
    return order


@transaction.atomic
def change_status(order, new_status, by=None, note=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if new_status == order.status:
        return order
    if new_status not in Order.Status.values:
        raise ValueError("Trạng thái không hợp lệ.")
    if new_status not in order.TRANSITIONS.get(order.status, []):
        raise ValueError(f"Không thể chuyển từ “{order.get_status_display()}” sang “{Order.Status(new_status).label}”.")
    if new_status == Order.Status.SHIPPING and not (order.delivery_method and order.delivery_method.is_pickup):
        if not (order.carrier.strip() and order.tracking_number.strip()):
            raise ValueError("Cần nhập đơn vị vận chuyển và mã vận đơn (mục “Vận chuyển”) trước khi chuyển sang “Đang giao”.")
    old = order.status
    order.status = new_status
    if new_status in (Order.Status.CANCELLED, Order.Status.RETURNED):
        _restock(order)
        if new_status == Order.Status.CANCELLED and order.coupon_id:
            # The voucher was never really consumed — give the slot back.
            Coupon.objects.filter(pk=order.coupon_id, used_count__gt=0).update(used_count=F("used_count") - 1)
        if order.payment_status == Order.PaymentStatus.PAID:
            order.payment_status = Order.PaymentStatus.REFUNDED
            note = (note + " — " if note else "") + "Hoàn tiền cho khách"
    if new_status in (Order.Status.DELIVERED, Order.Status.COMPLETED) and order.payment_method == Order.PaymentMethod.COD:
        if order.payment_status != Order.PaymentStatus.PAID:
            order.payment_status = Order.PaymentStatus.PAID
            order.paid_at = timezone.now()
    order.save()
    OrderStatusHistory.objects.create(order=order, status=new_status, note=note, changed_by=by)
    log.info("Order %s: %s -> %s", order.code, old, new_status)
    transaction.on_commit(lambda: send_order_email(order, f"Cập nhật đơn hàng: {order.get_status_display()}"))
    return order


def _restock(order):
    for item in order.items.all():
        if item.product_id:
            Product.objects.filter(pk=item.product_id).update(
                stock=F("stock") + item.quantity, sold_count=F("sold_count") - item.quantity
            )


def mark_paid(order, note="Thanh toán online thành công"):
    """Idempotent: safe to call from both the return URL and the IPN callback.

    If the order was cancelled before the money arrived (e.g. the shopper
    cancelled in another tab, or the unpaid-order job expired it) we must not
    resurrect it: the payment is recorded as REFUNDED so staff refund it.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.payment_status in (Order.PaymentStatus.PAID, Order.PaymentStatus.REFUNDED):
            return order, False
        order.paid_at = timezone.now()
        if order.status in (Order.Status.CANCELLED, Order.Status.RETURNED):
            order.payment_status = Order.PaymentStatus.REFUNDED
            note = f"{note} — đơn đã huỷ trước đó, cần hoàn tiền cho khách"
            subject = "Đơn đã huỷ — chúng tôi sẽ hoàn tiền"
            log.warning("Payment received for cancelled order %s — refund required", order.code)
        else:
            order.payment_status = Order.PaymentStatus.PAID
            subject = "Thanh toán thành công"
            if order.status == Order.Status.PENDING:
                order.status = Order.Status.CONFIRMED
        order.save()
        OrderStatusHistory.objects.create(order=order, status=order.status, note=note)
    send_order_email(order, subject)
    return order, True


@transaction.atomic
def expire_unpaid_orders(max_age_minutes=None):
    """Cancel online-payment orders that were never paid, releasing their stock.

    Run periodically (``manage.py expire_unpaid_orders``). Bank transfers get a
    longer window because staff reconcile them by hand.
    """
    max_age = max_age_minutes or settings.UNPAID_ORDER_TIMEOUT_MINUTES
    now = timezone.now()
    cutoffs = {
        Order.PaymentMethod.VNPAY: now - timezone.timedelta(minutes=max_age),
        Order.PaymentMethod.MOMO: now - timezone.timedelta(minutes=max_age),
        Order.PaymentMethod.BANK: now - timezone.timedelta(hours=24),
    }
    expired = []
    for method, cutoff in cutoffs.items():
        qs = Order.objects.filter(
            payment_method=method, status=Order.Status.PENDING, created_at__lt=cutoff
        ).exclude(payment_status=Order.PaymentStatus.PAID)
        for order in qs:
            change_status(order, Order.Status.CANCELLED, note="Tự động huỷ: quá hạn thanh toán")
            expired.append(order.code)
    return expired


def send_order_email(order, subject):
    try:
        body = render_to_string("emails/order_update.txt", {"order": order, "site_url": settings.SITE_URL})
        send_mail(f"[LevelUp Gear] {subject} #{order.code}", body, None, [order.email], fail_silently=True)
    except Exception:  # never break checkout because of e-mail
        log.exception("Could not send e-mail for %s", order.code)
