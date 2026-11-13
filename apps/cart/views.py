from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.models import Product
from apps.orders.services import drop_invalid_coupon, quote, resolve_coupon
from apps.recommendations.engine import frequently_bought_together_for_cart

from config.utils import safe_next

from . import services


def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", "")


def _qty(request, default=1):
    try:
        return max(0, min(int(request.POST.get("quantity", default)), 99))
    except (TypeError, ValueError):
        return default


def cart_detail(request):
    cart = services.get_cart(request)
    dropped = drop_invalid_coupon(cart, request.user)
    if dropped:
        messages.warning(request, dropped)
    q = quote(cart, user=request.user) if cart else None
    suggestions = frequently_bought_together_for_cart(cart, limit=4) if cart else []
    return render(request, "cart/detail.html", {"cart": cart, "quote": q, "suggestions": suggestions})


@require_POST
def add(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    cart = services.get_cart(request, create=True)
    item, msg = services.add_item(cart, product, _qty(request))
    if _wants_json(request):
        return JsonResponse({"ok": item is not None, "capped": bool(msg), "message": msg or f"Đã thêm “{product.name}” vào giỏ.", "cart_count": cart.total_quantity})
    if item is None or msg:
        messages.warning(request, msg)
    else:
        messages.success(request, f"Đã thêm “{product.name}” vào giỏ hàng.")
    if request.POST.get("buy_now"):
        return redirect("orders:checkout")
    return redirect(safe_next(request, "cart:detail"))


@require_POST
def update(request, product_id):
    cart = services.get_cart(request)
    msg = dropped = None
    if cart:
        _, msg = services.set_quantity(cart, product_id, _qty(request))
        dropped = drop_invalid_coupon(cart, request.user)
        if dropped:
            messages.warning(request, dropped)
            if msg:
                messages.warning(request, msg)
    if _wants_json(request) and cart:
        q = quote(cart, user=request.user)
        line = next((l for l in q["lines"] if l.product_id == product_id), None)
        return JsonResponse(
            {
                "cart_count": cart.total_quantity,
                "line_total": line.line_total if line else 0,
                "quantity": line.quantity if line else 0,
                "subtotal": q["subtotal"],
                "discount": q["discount"],
                "total": q["total"],
                "free_ship_gap": q["free_ship_gap"],
                "message": msg,
                "reload": bool(dropped),  # coupon block must be re-rendered; the warning shows after reload
            }
        )
    if msg and not dropped:
        messages.warning(request, msg)
    return redirect("cart:detail")


@require_POST
def remove(request, product_id):
    cart = services.get_cart(request)
    if cart:
        services.remove_item(cart, product_id)
        messages.info(request, "Đã xoá sản phẩm khỏi giỏ.")
    return redirect("cart:detail")


@require_POST
def apply_coupon(request):
    cart = services.get_cart(request)
    if not cart:
        return redirect("cart:detail")
    code = request.POST.get("code", "").strip().upper()
    if request.POST.get("remove"):
        cart.coupon_code = ""
        cart.save()
        messages.info(request, "Đã gỡ mã giảm giá.")
        return redirect(safe_next(request, "cart:detail"))
    coupon, msg = resolve_coupon(code, cart.subtotal, request.user)
    if coupon:
        cart.coupon_code = coupon.code
        cart.save()
        messages.success(request, f"{msg} ({coupon.description or coupon.code})")
    else:
        messages.error(request, msg or "Mã không hợp lệ.")
    return redirect(safe_next(request, "cart:detail"))
