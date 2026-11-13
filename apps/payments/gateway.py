"""Payment gateway adapters.

Two gateways share the same signing scheme (HMAC-SHA512 over the sorted,
URL-encoded query string — the VNPay 2.1.0 specification):

* ``vnpay`` — real VNPay sandbox. Needs VNPAY_TMN_CODE + VNPAY_HASH_SECRET.
* ``mock``  — built-in simulator hosted by this site, so the whole online
  payment flow (redirect → bank page → signed callback → IPN) can be demoed
  without merchant credentials. Used for VNPay when keys are absent and for
  MoMo — but only while ``settings.ALLOW_MOCK_PAYMENTS`` is on (default: DEBUG),
  because a simulated payment marks the order paid without any money moving.
"""
import hashlib
import hmac
import secrets
import urllib.parse
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Payment

SUCCESS_CODE = "00"
CANCEL_CODE = "24"  # VNPay: customer cancelled
FAIL_CODE = "51"  # VNPay: insufficient balance (used for simulated failure)

# Banks offered on the simulated card page (code, name). VNPay's sandbox only accepts the NCB test card,
# so whichever bank is picked, the card number shown is that test card.
MOCK_BANKS = [
    ("NCB", "NCB — Ngân hàng Quốc Dân (thẻ test)"),
    ("VCB", "Vietcombank — Ngoại thương Việt Nam"),
    ("BIDV", "BIDV — Đầu tư và Phát triển Việt Nam"),
    ("CTG", "VietinBank — Công Thương Việt Nam"),
    ("AGRIBANK", "Agribank — Nông nghiệp và Phát triển Nông thôn"),
    ("TCB", "Techcombank — Kỹ Thương Việt Nam"),
    ("MB", "MB Bank — Quân Đội"),
    ("ACB", "ACB — Á Châu"),
    ("VPB", "VPBank — Việt Nam Thịnh Vượng"),
    ("TPB", "TPBank — Tiên Phong"),
    ("STB", "Sacombank — Sài Gòn Thương Tín"),
    ("VIB", "VIB — Quốc tế Việt Nam"),
    ("HDB", "HDBank — Phát triển TP.HCM"),
    ("SHB", "SHB — Sài Gòn – Hà Nội"),
    ("MSB", "MSB — Hàng Hải Việt Nam"),
    ("OCB", "OCB — Phương Đông"),
    ("SEAB", "SeABank — Đông Nam Á"),
    ("EIB", "Eximbank — Xuất Nhập khẩu Việt Nam"),
    ("LPB", "LPBank — Lộc Phát Việt Nam"),
    ("NAB", "Nam A Bank — Nam Á"),
]
MOCK_TEST_CARD = "9704 1985 2619 1432 198"

RESPONSE_MESSAGES = {
    "00": "Giao dịch thành công",
    "07": "Giao dịch bị nghi ngờ gian lận",
    "09": "Thẻ/Tài khoản chưa đăng ký Internet Banking",
    "11": "Hết hạn chờ thanh toán",
    "24": "Khách hàng huỷ giao dịch",
    "51": "Tài khoản không đủ số dư",
    "65": "Vượt quá hạn mức giao dịch trong ngày",
    "97": "Chữ ký không hợp lệ",
    "99": "Lỗi không xác định",
}


def _sign(params: dict, secret: str) -> str:
    query = urllib.parse.urlencode(sorted((k, v) for k, v in params.items() if k.startswith("vnp_") and k not in ("vnp_SecureHash", "vnp_SecureHashType")))
    return hmac.new(secret.encode(), query.encode(), hashlib.sha512).hexdigest()


def verify_signature(params: dict, secret: str) -> bool:
    received = params.get("vnp_SecureHash", "")
    return bool(received) and hmac.compare_digest(received.lower(), _sign(params, secret).lower())


class PaymentUnavailable(Exception):
    """No gateway may process this payment method in the current configuration."""


def vnpay_configured() -> bool:
    return settings.PAYMENT_MODE == "vnpay" and bool(settings.VNPAY["TMN_CODE"] and settings.VNPAY["HASH_SECRET"])


def active_gateway() -> str:
    return "vnpay" if vnpay_configured() else "mock"


def gateway_for(payment_method: str):
    """Gateway that will process ``payment_method`` online, or None if none may.

    Only VNPay has a real integration; MoMo exists solely in the simulator.
    """
    if payment_method == "vnpay" and vnpay_configured():
        return "vnpay"
    if payment_method in ("vnpay", "momo") and settings.ALLOW_MOCK_PAYMENTS:
        return "mock"
    return None


def available_payment_methods() -> list[str]:
    """Payment methods the checkout may offer right now."""
    from apps.orders.models import Order

    online = (Order.PaymentMethod.VNPAY, Order.PaymentMethod.MOMO)
    return [m for m in Order.PaymentMethod.values if m not in online or gateway_for(m)]


def secret_for(gateway: str) -> str:
    return settings.VNPAY["HASH_SECRET"] if gateway == "vnpay" else settings.MOCK_GATEWAY_SECRET


def create_payment(order, ip="127.0.0.1", return_url=None):
    gateway = gateway_for(order.payment_method)
    if gateway is None:
        raise PaymentUnavailable(order.payment_method)
    payment = Payment.objects.create(
        order=order,
        provider=order.payment_method,
        gateway=gateway,
        txn_ref=f"{order.code}-{secrets.token_hex(3)}",
        amount=order.total,
    )
    return payment, build_redirect_url(payment, ip, return_url)


def build_params(payment, ip, return_url):
    now = timezone.localtime()
    return {
        "vnp_Version": "2.1.0",
        "vnp_Command": "pay",
        "vnp_TmnCode": settings.VNPAY["TMN_CODE"] or "LEVELUP0",
        "vnp_Amount": str(payment.amount * 100),  # VNPay expects amount × 100
        "vnp_CurrCode": "VND",
        "vnp_TxnRef": payment.txn_ref,
        "vnp_OrderInfo": f"Thanh toan don hang {payment.order.code}",
        "vnp_OrderType": "other",
        "vnp_Locale": "vn",
        "vnp_ReturnUrl": return_url,
        "vnp_IpAddr": ip or "127.0.0.1",
        "vnp_CreateDate": now.strftime("%Y%m%d%H%M%S"),
        "vnp_ExpireDate": (now + timedelta(minutes=15)).strftime("%Y%m%d%H%M%S"),
    }


def build_redirect_url(payment, ip, return_url=None):
    # Prefer the URL of the host the shopper is actually on (built from the
    # request); SITE_URL is only a fallback for non-request contexts.
    return_url = return_url or settings.SITE_URL.rstrip("/") + reverse("payments:return")
    params = build_params(payment, ip, return_url)
    params["vnp_SecureHash"] = _sign(params, secret_for(payment.gateway))
    base = settings.VNPAY["PAYMENT_URL"] if payment.gateway == "vnpay" else reverse("payments:mock_gateway")
    return f"{base}?{urllib.parse.urlencode(params)}"


def mock_result_params(request_params: dict, outcome: str) -> dict:
    """Simulate the gateway's signed callback for the chosen outcome."""
    code = {"success": SUCCESS_CODE, "fail": FAIL_CODE, "cancel": CANCEL_CODE}[outcome]
    result = {
        "vnp_Amount": request_params["vnp_Amount"],
        "vnp_BankCode": "NCB" if outcome == "success" else "",
        "vnp_OrderInfo": request_params["vnp_OrderInfo"],
        "vnp_PayDate": timezone.localtime().strftime("%Y%m%d%H%M%S"),
        "vnp_ResponseCode": code,
        "vnp_TmnCode": request_params["vnp_TmnCode"],
        "vnp_TransactionNo": str(secrets.randbelow(10**8)).zfill(8) if outcome == "success" else "0",
        "vnp_TransactionStatus": code,
        "vnp_TxnRef": request_params["vnp_TxnRef"],
    }
    result["vnp_SecureHash"] = _sign(result, settings.MOCK_GATEWAY_SECRET)
    return result


def process_callback(params: dict):
    """Validate a gateway callback and update Payment/Order. Idempotent.

    Returns (payment|None, rsp_code, message) where rsp_code follows the VNPay
    IPN convention: 00 ok, 01 order not found, 02 already confirmed,
    04 invalid amount, 97 bad signature.
    """
    from apps.orders.services import mark_paid

    payment = Payment.objects.select_related("order").filter(txn_ref=params.get("vnp_TxnRef", "")).first()
    if not payment:
        return None, "01", "Order not found"
    if payment.gateway == "mock" and not settings.ALLOW_MOCK_PAYMENTS:
        # Simulated payments are switched off: nothing signed with the mock
        # secret may ever mark an order paid, whatever the signature says.
        return payment, "97", "Invalid signature"
    if not verify_signature(params, secret_for(payment.gateway)):
        return payment, "97", "Invalid signature"
    try:
        amount = int(params.get("vnp_Amount", "0")) // 100
    except ValueError:
        amount = -1
    if amount != payment.amount:
        return payment, "04", "Invalid amount"
    if payment.status != Payment.Status.PENDING:
        return payment, "02", "Order already confirmed"

    code = params.get("vnp_ResponseCode", "99")
    payment.response_code = code
    payment.gateway_txn_no = params.get("vnp_TransactionNo", "")
    payment.raw_response = {k: v for k, v in params.items() if k != "vnp_SecureHash"}
    if code == SUCCESS_CODE and params.get("vnp_TransactionStatus", SUCCESS_CODE) == SUCCESS_CODE:
        payment.status = Payment.Status.SUCCESS
        payment.save()
        mark_paid(payment.order, f"Thanh toán {payment.get_provider_display()} thành công (GD {payment.gateway_txn_no})")
    else:
        payment.status = Payment.Status.CANCELLED if code == CANCEL_CODE else Payment.Status.FAILED
        payment.save()
        order = payment.order
        if order.payment_status == order.PaymentStatus.UNPAID:
            order.payment_status = order.PaymentStatus.FAILED
            order.save(update_fields=["payment_status", "updated_at"])
    return payment, "00", "Confirm Success"
