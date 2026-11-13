import base64
import io
import urllib.parse

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.orders.models import Order
from apps.orders.views import can_view_order
from config.utils import client_ip

from . import gateway, vietqr
from .models import Payment


@require_POST
def start(request, code):
    """Create a payment attempt and redirect to the gateway (or bank-transfer page)."""
    order = get_object_or_404(Order, code=code)
    if not can_view_order(request, order):
        raise Http404
    if not order.needs_online_payment or order.status == Order.Status.CANCELLED:
        messages.info(request, "Đơn hàng không cần thanh toán thêm.")
        return redirect(order.get_absolute_url())
    if order.payment_method == Order.PaymentMethod.BANK:
        return redirect("payments:bank_transfer", code=order.code)
    return_url = request.build_absolute_uri(reverse("payments:return"))
    try:
        _, url = gateway.create_payment(order, client_ip(request), return_url=return_url)
    except gateway.PaymentUnavailable:
        messages.error(
            request,
            f"Hiện chưa thể thanh toán qua {order.get_payment_method_display()}. "
            "Vui lòng huỷ đơn và đặt lại với phương thức khác, hoặc liên hệ hotline.",
        )
        return redirect(order.get_absolute_url())
    return redirect(url)


@require_GET
def bank_transfer(request, code):
    order = get_object_or_404(Order, code=code)
    if not can_view_order(request, order):
        raise Http404
    bank = settings.BANK_TRANSFER
    transfer_note = f"LEVELUP {order.code}"
    payload = vietqr.build_payload(bank["bin"], bank["account_no"], order.total, transfer_note)
    qr_data_uri = ""
    try:
        import qrcode

        img = qrcode.make(payload, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        pass
    return render(
        request,
        "payments/bank_transfer.html",
        {"order": order, "bank": bank, "transfer_note": transfer_note, "qr": qr_data_uri, "qr_payload": payload,
         "can_simulate": settings.ALLOW_MOCK_PAYMENTS and order.payment_status == Order.PaymentStatus.UNPAID
         and order.status != Order.Status.CANCELLED},
    )


@require_POST
def bank_transfer_simulate(request, code):
    """Demo only: stands in for the bank's "money received" notification (what a service such as
    Casso / SePay / PayOS would send on a real shop), so the transfer flow can be tested end to end."""
    if not settings.ALLOW_MOCK_PAYMENTS:
        raise Http404
    order = get_object_or_404(Order, code=code, payment_method=Order.PaymentMethod.BANK)
    if not can_view_order(request, order):
        raise Http404
    from apps.orders import services as order_services

    order_services.mark_paid(order, f"Mô phỏng: ngân hàng báo đã nhận {order.total:,}₫ — nội dung LEVELUP {order.code}".replace(",", "."))
    messages.success(request, "Mô phỏng: ngân hàng đã báo nhận tiền, đơn được chuyển sang “Đã thanh toán”.")
    return redirect("payments:bank_transfer", code=order.code)


@require_http_methods(["GET", "POST"])
def mock_gateway(request):
    """Simulated payment page (stands in for VNPay / MoMo in the demo)."""
    if not settings.ALLOW_MOCK_PAYMENTS:
        raise Http404
    params = request.GET.dict()
    payment = Payment.objects.select_related("order").filter(txn_ref=params.get("vnp_TxnRef", ""), gateway="mock").first()
    if not payment or not gateway.verify_signature(params, gateway.secret_for("mock")):
        return invalid_transaction(request)
    if request.method == "POST":
        outcome = request.POST.get("outcome")
        if outcome not in ("success", "fail", "cancel"):
            return HttpResponseBadRequest("Thao tác không hợp lệ.")
        result = gateway.mock_result_params(params, outcome)
        # Simulate the server-to-server IPN first (as a real gateway would)…
        gateway.process_callback(result)
        # …then send the shopper's browser back to the return URL.
        return redirect(params["vnp_ReturnUrl"] + "?" + urllib.parse.urlencode(result))
    return render(
        request,
        "payments/mock_gateway.html",
        {"payment": payment, "order": payment.order, "amount": int(params["vnp_Amount"]) // 100,
         "banks": gateway.MOCK_BANKS, "test_card": gateway.MOCK_TEST_CARD},
    )


def invalid_transaction(request):
    """Shown when gateway parameters were altered or do not match a payment: says so plainly, reveals nothing."""
    return render(request, "payments/result.html", {"invalid": True}, status=400)


@require_GET
def payment_return(request):
    """Browser lands here after paying. We verify the signature again before showing anything."""
    params = request.GET.dict()
    payment, rsp, _ = gateway.process_callback(params)
    if payment is None or rsp in ("97", "04"):
        return invalid_transaction(request)
    payment.refresh_from_db()
    order = payment.order
    code = params.get("vnp_ResponseCode", "99")
    return render(
        request,
        "payments/result.html",
        {
            "order": order,
            "payment": payment,
            "success": payment.status == Payment.Status.SUCCESS,
            "message": gateway.RESPONSE_MESSAGES.get(code, gateway.RESPONSE_MESSAGES["99"]),
        },
    )


@csrf_exempt
@require_GET
def ipn(request):
    """VNPay Instant Payment Notification endpoint (server-to-server)."""
    payment, rsp, msg = gateway.process_callback(request.GET.dict())
    return JsonResponse({"RspCode": rsp, "Message": msg})
