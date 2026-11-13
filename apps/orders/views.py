import hmac

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import Address
from apps.catalog.models import Review
from apps.cart.services import add_item as add_cart_item
from apps.cart.services import get_cart

from . import services
from config.utils import client_ip

from .forms import CheckoutForm, OrderLookupForm
from .models import DeliveryMethod, Order


def can_view_order(request, order):
    if request.user.is_authenticated and (order.user_id == request.user.id or request.user.is_staff):
        return True
    token = request.GET.get("t") or request.session.get(f"order_token_{order.code}", "")
    return bool(token) and hmac.compare_digest(token, order.access_token)


def order_url(request, order):
    """Order page link: the signed-in owner doesn't need the access token in the URL."""
    if request.user.is_authenticated and order.user_id == request.user.id:
        return reverse("orders:detail", args=[order.code])
    return order.get_absolute_url()


def _initial_from_user(user):
    if not user.is_authenticated:
        return {"payment_method": "cod"}
    initial = {"full_name": user.get_full_name(), "email": user.email, "phone": user.phone, "payment_method": "cod"}
    addr = user.addresses.first()
    if addr:
        initial.update(full_name=addr.full_name, phone=addr.phone, province=addr.province, ward=addr.ward, street=addr.street)
    return initial


def _pk_or_none(value):
    """Query-string ids come from the browser — never let junk reach the ORM."""
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def checkout(request):
    cart = get_cart(request)
    if not cart or not cart.items.exists():
        messages.info(request, "Giỏ hàng của bạn đang trống.")
        return redirect("cart:detail")
    dropped = services.drop_invalid_coupon(cart, request.user)
    if dropped:
        messages.warning(request, dropped + " Vui lòng kiểm tra lại tổng tiền trước khi đặt hàng.")

    form = CheckoutForm(request.POST or None, initial=_initial_from_user(request.user))
    if request.method == "POST" and not dropped and form.is_valid():
        data = form.cleaned_data
        try:
            order = services.place_order(cart=cart, user=request.user, data=data, ip=client_ip(request) or None)
        except services.CheckoutError as e:
            messages.error(request, str(e))
            return redirect("cart:detail")
        if request.user.is_authenticated and data.get("save_address"):
            Address.objects.get_or_create(
                user=request.user,
                street=data["street"],
                ward=data["ward"],
                province=data["province"],
                defaults={"full_name": data["full_name"], "phone": data["phone"], "is_default": not request.user.addresses.exists()},
            )
        request.session[f"order_token_{order.code}"] = order.access_token
        if order.payment_method == Order.PaymentMethod.COD:
            return redirect("orders:success", code=order.code)
        if order.payment_method == Order.PaymentMethod.BANK:
            return redirect("payments:bank_transfer", code=order.code)
        # Online payment: auto-submit to the gateway from the success page
        return redirect(f"{order.get_absolute_url()}&pay=1")

    province = form.data.get("province") or form.initial.get("province") or "TP. Hồ Chí Minh"
    methods = DeliveryMethod.objects.filter(is_active=True)
    selected_method = None
    method_pk = _pk_or_none(form.data.get("delivery_method"))
    if method_pk:
        selected_method = methods.filter(pk=method_pk).first()
    selected_method = selected_method or methods.first()
    q = services.quote(cart, selected_method, province, request.user)
    method_fees = [
        {"method": m, "fee": services.shipping_fee(m, province, q["subtotal"], q["weight"], q["coupon"]), "available": m.available_for(province)}
        for m in methods
    ]
    return render(request, "orders/checkout.html", {"form": form, "quote": q, "method_fees": method_fees, "selected_method": selected_method})


@require_GET
def checkout_quote(request):
    """AJAX: recompute shipping & total when the shopper changes province/method."""
    cart = get_cart(request)
    if not cart:
        return JsonResponse({"error": "empty"}, status=400)
    province = request.GET.get("province", "")
    method_pk = _pk_or_none(request.GET.get("method"))
    method = DeliveryMethod.objects.filter(pk=method_pk, is_active=True).first() if method_pk else None
    q = services.quote(cart, method, province, request.user)
    fees = {}
    for m in DeliveryMethod.objects.filter(is_active=True):
        fees[m.pk] = {"fee": services.shipping_fee(m, province, q["subtotal"], q["weight"], q["coupon"]), "available": m.available_for(province)}
    return JsonResponse({"subtotal": q["subtotal"], "discount": q["discount"], "shipping_fee": q["shipping_fee"], "total": q["total"], "fees": fees})


def success(request, code):
    order = get_object_or_404(Order, code=code)
    if not can_view_order(request, order):
        raise Http404
    return render(request, "orders/success.html", {"order": order})


def detail(request, code):
    order = get_object_or_404(Order.objects.select_related("delivery_method"), code=code)
    if not can_view_order(request, order):
        raise Http404
    request.session[f"order_token_{order.code}"] = order.access_token
    is_owner = request.user.is_authenticated and order.user_id == request.user.id
    received = order.status in (Order.Status.DELIVERED, Order.Status.COMPLETED)
    items = list(order.items.select_related("product").prefetch_related("product__images"))
    if is_owner and received:
        reviewed = set(Review.objects.filter(user=request.user, product_id__in=[i.product_id for i in items]).values_list("product_id", flat=True))
        for i in items:
            i.can_review = i.product is not None and i.product.is_active and i.product_id not in reviewed
    return render(
        request,
        "orders/detail.html",
        {
            "order": order,
            "items": items,
            "auto_pay": request.GET.get("pay") == "1",
            "is_owner": is_owner,
            "received": received,
            "can_buy_again": order.status in (Order.Status.DELIVERED, Order.Status.COMPLETED, Order.Status.CANCELLED, Order.Status.RETURNED),
        },
    )


@require_POST
def cancel(request, code):
    order = get_object_or_404(Order, code=code)
    if not can_view_order(request, order):
        raise Http404
    if order.status == Order.Status.CANCELLED:
        messages.info(request, f"Đơn {order.code} đã được huỷ trước đó.")
    elif not order.can_cancel:
        messages.error(request, "Đơn hàng đã được xử lý, không thể huỷ. Vui lòng liên hệ hotline.")
    else:
        reason = request.POST.get("reason", "")[:200]
        services.change_status(order, Order.Status.CANCELLED, by=request.user if request.user.is_authenticated else None, note=f"Khách huỷ: {reason}")
        messages.success(request, f"Đã huỷ đơn {order.code}.")
    return redirect(order_url(request, order))


@require_POST
def buy_again(request, code):
    """Put every still-available product of a past order back into the cart."""
    order = get_object_or_404(Order, code=code)
    if not can_view_order(request, order):
        raise Http404
    cart = get_cart(request, create=True)
    added, skipped = 0, []
    for item in order.items.select_related("product"):
        product = item.product
        if product is None or not product.is_active:
            skipped.append(item.product_name)
            continue
        line, msg = add_cart_item(cart, product, item.quantity)
        if line is None:
            skipped.append(item.product_name)
        else:
            added += 1
            if msg:
                messages.warning(request, msg)
    if added:
        messages.success(request, f"Đã thêm {added} sản phẩm của đơn {order.code} vào giỏ hàng.")
    if skipped:
        messages.warning(request, "Không thể thêm (ngừng bán hoặc hết hàng): " + ", ".join(skipped) + ".")
    return redirect("cart:detail" if added else order_url(request, order))


def lookup(request):
    """Guests track orders by code + email/phone. Rate-limited to stop enumeration."""
    form = OrderLookupForm(request.POST or None)
    if request.method == "POST":
        key = f"lookup:{client_ip(request)}"
        attempts = cache.get(key, 0)
        if attempts >= 10:
            messages.error(request, "Bạn tra cứu quá nhiều lần. Vui lòng thử lại sau 10 phút.")
        elif form.is_valid():
            cache.set(key, attempts + 1, 600)
            c = form.cleaned_data["contact"].strip().lower()
            order = Order.objects.filter(code__iexact=form.cleaned_data["code"].strip()).first()
            if order and c in (order.email.lower(), order.phone):
                return redirect(order.get_absolute_url())
            messages.error(request, "Không tìm thấy đơn hàng khớp với thông tin đã nhập.")
    return render(request, "orders/lookup.html", {"form": form})


@login_required
def my_orders(request):
    orders = request.user.orders.prefetch_related("items")
    status = request.GET.get("status")
    if status:
        orders = orders.filter(status=status)
    return render(request, "orders/my_orders.html", {"orders": orders, "statuses": Order.Status.choices, "current": status})
