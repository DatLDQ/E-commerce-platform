"""Shopping-assistant chatbot (Part 5 — Chatbot).

Pipeline for each message:
  1. normalise (lowercase, strip Vietnamese accents, punctuation -> spaces)
  2. extract entities: order code, budget, product category, brand, use-case tags
  3. detect intent by whole-word keyword scoring (order status, shipping,
     returns, warranty, payment, promotions, contact, product search…)
  3b. follow-ups ("Rẻ hơn chút", "Loại không dây thì sao?") reuse the
     entities of the previous recommendation kept in the session
  4. answer from live data (orders, products, coupons, delivery methods)
     or from the admin-editable FAQ table
  5. optional: if GEMINI_API_KEY is configured, unknown questions go to an LLM
     that is grounded with store policies and a few matching products.

Works completely offline by default — no API key required for the demo.
"""
import json
import logging
import re
import urllib.request

from django.conf import settings
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Brand, Category, Product
from apps.catalog.utils import strip_accents, vnd
from apps.orders.models import Coupon, DeliveryMethod, Order

from .models import FAQ

log = logging.getLogger("apps.chatbot")

INTENTS = {
    "greeting": ["xin chao", "chao", "hello", "hi", "alo", "hey"],
    "thanks": ["cam on", "thank", "tks", "thanks"],
    "order_status": ["don hang", "don cua toi", "kiem tra don", "tra cuu", "ma don", "giao chua", "toi dau roi", "trang thai"],
    "shipping": ["phi ship", "phi van chuyen", "giao hang", "ship", "bao lau", "may ngay", "giao nhanh", "hoa toc", "nhan tai cua hang"],
    "returns": ["doi tra", "tra hang", "hoan tien", "doi hang", "loi", "hong"],
    "warranty": ["bao hanh"],
    "payment": ["thanh toan", "tra gop", "cod", "vnpay", "momo", "chuyen khoan", "the visa", "atm"],
    "promotion": ["khuyen mai", "giam gia", "ma giam", "voucher", "coupon", "sale", "uu dai"],
    "contact": ["lien he", "hotline", "nhan vien", "tu van vien", "gap nguoi", "dia chi cua hang", "showroom"],
    "recommend": ["tu van", "goi y", "nen mua", "chon", "phu hop", "tot nhat", "recommend", "mua", "can tim", "tim", "co ban", "con hang"],
}

CATEGORY_HINTS = {
    "chuot": "chuot", "mouse": "chuot",
    "ban phim": "ban-phim", "keyboard": "ban-phim", "phim co": "ban-phim",
    "tai nghe": "tai-nghe", "headset": "tai-nghe", "headphone": "tai-nghe",
    "man hinh": "man-hinh", "monitor": "man-hinh",
    "ghe": "ghe-gaming", "chair": "ghe-gaming",
    "lot chuot": "lot-chuot", "mousepad": "lot-chuot", "pad": "lot-chuot",
    "tay cam": "tay-cam", "controller": "tay-cam", "gamepad": "tay-cam",
    "micro": "micro-stream", "mic": "micro-stream", "webcam": "micro-stream", "stream": "micro-stream",
}

TAG_HINTS = {
    "fps": "fps", "ban sung": "fps", "valorant": "fps", "cs2": "fps", "csgo": "fps", "pubg": "fps",
    "moba": "moba", "lien minh": "moba", "lol": "moba", "dota": "moba", "lien quan": "moba",
    "khong day": "wireless", "wireless": "wireless", "bluetooth": "wireless",
    "rgb": "rgb", "led": "rgb", "nhe": "lightweight", "sieu nhe": "lightweight",
    "stream": "streaming", "streamer": "streaming", "van phong": "office", "dua xe": "racing",
    "144hz": "high-refresh", "165hz": "high-refresh", "240hz": "high-refresh",
}

TAG_LABELS = {
    "fps": "FPS", "moba": "MOBA", "wireless": "không dây", "rgb": "RGB", "lightweight": "siêu nhẹ",
    "streaming": "stream", "office": "văn phòng", "racing": "đua xe", "high-refresh": "tần số quét cao",
}

# Longest keys first so "lot chuot" (mousepad) wins over "chuot" (mouse)
CATEGORY_KEYS = sorted(CATEGORY_HINTS, key=len, reverse=True)

CHEAPER_CUES = ["re hon", "gia thap hon", "tiet kiem hon", "mem hon"]
PRICIER_CUES = ["dat hon", "cao cap hon", "xin hon", "tot hon", "xin xo hon"]
FOLLOW_UP_CUES = CHEAPER_CUES + PRICIER_CUES + ["thi sao", "loai khac", "con loai", "mau khac", "con gi", "con mau"]
CONTEXT_TTL = 30 * 60  # seconds a recommendation context stays usable

ORDER_CODE_RE = re.compile(r"\bLU\d{6}[0-9A-F]{6}\b", re.I)


def normalize(text):
    """Accent-free, lowercase, punctuation-free text padded with spaces."""
    return " " + re.sub(r"[^a-z0-9]+", " ", strip_accents(text)).strip() + " "


def has(norm, phrase):
    """Whole-word match — 'hong' must not fire inside 'khong', nor 'cod' inside 'code'."""
    return f" {phrase} " in norm


def parse_budget(text):
    """'duoi 2 trieu' -> (None, 2_000_000); 'tam 1tr5' -> (1.2M, 1.8M); '500k' -> (400k, 600k)."""
    t = text.replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(tr|trieu|cu|m)\s*(\d)?\b", t)
    amount = None
    if m:
        amount = float(m.group(1)) * 1_000_000
        if m.group(3):
            amount += int(m.group(3)) * 100_000
    else:
        m = re.search(r"(\d+)\s*(k|nghin|ngan)\b", t)
        if m:
            amount = int(m.group(1)) * 1000
        else:
            m = re.search(r"\b(\d{6,8})\b", t)
            if m:
                amount = int(m.group(1))
    if amount is None:
        return None, None
    amount = int(amount)
    if re.search(r"duoi|toi da|khong qua|max|<", t):
        return None, amount
    if re.search(r"tren|tu .* tro len|>|it nhat", t):
        return amount, None
    return int(amount * 0.75), int(amount * 1.2)


def extract(text):
    n = normalize(text)
    cat_slug = next((CATEGORY_HINTS[k] for k in CATEGORY_KEYS if has(n, k)), None)
    brand = None
    for b in sorted(Brand.objects.all(), key=lambda b: len(b.name), reverse=True):
        if has(n, normalize(b.name).strip()):
            brand = b
            break
    tags = sorted({tag for k, tag in TAG_HINTS.items() if has(n, k)})
    lo, hi = parse_budget(" " + strip_accents(text) + " ")
    code = ORDER_CODE_RE.search(text)
    return {"norm": n, "category": cat_slug, "brand": brand, "tags": tags, "min": lo, "max": hi, "order_code": code.group(0).upper() if code else None}


def detect_intent(e):
    n = e["norm"]
    if e["order_code"]:
        return "order_status"
    scores = {k: sum(1 for kw in kws if has(n, kw)) for k, kws in INTENTS.items()}
    # Product entities hint at a product search, but a service keyword
    # ("chuột bị hỏng", "bảo hành tai nghe") must still win over a bare category.
    scores["recommend"] += (1 if e["category"] else 0) + (1 if e["tags"] else 0) + (2 if e["min"] or e["max"] else 0)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def product_card(p):
    img = p.main_image
    return {"name": p.name, "url": p.get_absolute_url(), "price": vnd(p.current_price), "old_price": vnd(p.price) if p.sale_price else "", "image": img.image.url if img else ""}


def find_products(e, limit=4):
    qs = Product.objects.active().filter(stock__gt=0).annotate(eff=Coalesce("sale_price", "price")).prefetch_related("images")
    if e["category"]:
        cat = Category.objects.filter(slug=e["category"]).first()
        if cat:
            qs = qs.filter(category=cat)
    if e["brand"]:
        qs = qs.filter(brand=e["brand"])
    if e["min"]:
        qs = qs.filter(eff__gte=e["min"])
    if e["max"]:
        qs = qs.filter(eff__lte=e["max"])
    tagged = qs
    for t in e["tags"]:
        tagged = tagged.filter(tags__icontains=t)
    result = list(tagged.order_by("-sold_count", "-view_count")[:limit])
    if not result:  # relax tag constraints
        result = list(qs.order_by("-sold_count")[:limit])
    return result


def _follow_up(e, intent, ctx):
    """Merge a short follow-up message with the previous recommendation context."""
    if not ctx or intent not in ("unknown", "recommend") or e["category"]:
        return None
    n = e["norm"]
    cheaper = any(has(n, c) for c in CHEAPER_CUES)
    pricier = any(has(n, c) for c in PRICIER_CUES)
    if not (cheaper or pricier or e["tags"] or e["brand"] or e["min"] or e["max"] or any(has(n, c) for c in FOLLOW_UP_CUES)):
        return None
    merged = dict(e)
    merged["category"] = ctx.get("category")
    merged["brand"] = e["brand"] or Brand.objects.filter(pk=ctx.get("brand")).first()
    merged["tags"] = sorted(set(e["tags"]) | set(ctx.get("tags", [])))
    if cheaper and ctx.get("low"):
        merged["min"], merged["max"] = None, ctx["low"] - 1
    elif pricier and ctx.get("high"):
        merged["min"], merged["max"] = ctx["high"] + 1, None
    elif not (e["min"] or e["max"]):
        merged["min"], merged["max"] = ctx.get("min"), ctx.get("max")
    return merged


def _load_context(request):
    ctx = request.session.get("chat_ctx")
    if ctx and timezone.now().timestamp() - ctx.get("at", 0) < CONTEXT_TTL:
        return ctx
    return None


def _save_context(request, e, products):
    prices = [p.current_price for p in products]
    request.session["chat_ctx"] = {
        "category": e["category"], "brand": e["brand"].pk if e["brand"] else None, "tags": e["tags"],
        "min": e["min"], "max": e["max"], "low": min(prices), "high": max(prices), "at": timezone.now().timestamp(),
    }


def answer(text, request):
    e = extract(text)
    intent = detect_intent(e)
    merged = _follow_up(e, intent, _load_context(request))
    if merged:
        e, intent = merged, "recommend"
    out = {"intent": intent, "reply": "", "products": [], "quick_replies": [], "links": []}
    biz = settings.BUSINESS_INFO

    if intent == "greeting":
        name = request.user.first_name if request.user.is_authenticated else "game thủ"
        out["reply"] = f"Chào {name}! Mình là LevelBot 🎮 Mình có thể tư vấn gear theo ngân sách, kiểm tra đơn hàng, phí ship và chính sách đổi trả."
        out["quick_replies"] = ["Chuột FPS dưới 1 triệu", "Phí ship bao nhiêu?", "Có mã giảm giá không?", "Kiểm tra đơn hàng"]

    elif intent == "thanks":
        out["reply"] = "Không có gì nha! Chúc bạn leo rank thật nhanh 🚀"

    elif intent == "order_status":
        code = e["order_code"]
        order = None
        if code:
            order = Order.objects.filter(code=code).first()
            allowed = order and (
                (request.user.is_authenticated and order.user_id == request.user.id)
                or request.session.get(f"order_token_{order.code}") == order.access_token
            )
            if order and allowed:
                out["reply"] = (
                    f"Đơn {order.code}: {order.get_status_display()} — thanh toán: {order.get_payment_status_display()}. "
                    f"Tổng {vnd(order.total)}, giao bằng {order.delivery_method.name}."
                    + (f" Mã vận đơn: {order.tracking_number} ({order.carrier})." if order.tracking_number else "")
                )
                out["links"] = [{"text": "Xem chi tiết đơn", "url": reverse("orders:detail", args=[order.code])}]  # already allowed: no token in the link
            else:
                out["reply"] = "Để bảo mật, bạn vui lòng tra cứu đơn bằng mã đơn + email/số điện thoại đặt hàng nhé."
                out["links"] = [{"text": "Tra cứu đơn hàng", "url": reverse("orders:lookup")}]
        elif request.user.is_authenticated and request.user.orders.exists():
            recent = request.user.orders.all()[:3]
            out["reply"] = "Các đơn gần đây của bạn:\n" + "\n".join(f"• {o.code} — {o.get_status_display()} — {vnd(o.total)}" for o in recent)
            out["links"] = [{"text": "Tất cả đơn hàng", "url": reverse("orders:mine")}]
        else:
            out["reply"] = "Bạn gửi mình mã đơn (dạng LU…) hoặc tra cứu tại trang Tra cứu đơn hàng nhé."
            out["links"] = [{"text": "Tra cứu đơn hàng", "url": reverse("orders:lookup")}]

    elif intent == "shipping":
        lines = []
        for m in DeliveryMethod.objects.filter(is_active=True):
            fee = "miễn phí" if m.is_pickup else f"từ {vnd(m.base_fee)}"
            area = f" (chỉ {m.only_provinces})" if m.only_provinces else ""
            lines.append(f"• {m.name}: {fee}, {m.eta_label()}{area}")
        out["reply"] = (
            "Các hình thức giao hàng:\n" + "\n".join(lines)
            + f"\nMiễn phí giao tiêu chuẩn cho đơn từ {vnd(settings.FREE_SHIPPING_THRESHOLD)}. Ngoài TP.HCM cộng phụ phí vùng."
        )
        out["links"] = [{"text": "Chính sách vận chuyển", "url": reverse("pages:policy", args=["van-chuyen"])}]

    elif intent == "returns":
        out["reply"] = (
            "Đổi trả trong 7 ngày nếu sản phẩm lỗi do nhà sản xuất (đổi mới) hoặc 3 ngày nếu không vừa ý "
            "(sản phẩm còn nguyên seal, phí 10%). Hoàn tiền trong 3–5 ngày làm việc qua phương thức bạn đã thanh toán."
        )
        out["links"] = [{"text": "Chính sách đổi trả", "url": reverse("pages:policy", args=["doi-tra"])}]

    elif intent == "warranty":
        out["reply"] = "Tất cả sản phẩm chính hãng, bảo hành 12–36 tháng tuỳ hãng (ghi ở trang sản phẩm). Bạn mang sản phẩm + mã đơn tới showroom hoặc gửi bưu điện, LevelUp Gear chịu phí ship 2 chiều."
        out["links"] = [{"text": "Chính sách bảo hành", "url": reverse("pages:policy", args=["bao-hanh"])}]

    elif intent == "payment":
        out["reply"] = "LevelUp Gear nhận: COD (trả tiền khi nhận), VNPay (ATM/Visa/Master/QR), ví MoMo và chuyển khoản VietQR. Thanh toán online được xác thực bằng chữ ký HMAC-SHA512, shop không lưu thông tin thẻ của bạn."

    elif intent == "promotion":
        now = timezone.now()
        coupons = Coupon.objects.filter(is_active=True, valid_from__lte=now).exclude(valid_to__lt=now)[:5]
        if coupons:
            out["reply"] = "Mã đang có hiệu lực:\n" + "\n".join(f"• {c.code}: {c.description}" for c in coupons)
        else:
            out["reply"] = "Hiện chưa có mã giảm giá, bạn đăng ký nhận tin để không bỏ lỡ nhé!"
        sale = Product.objects.active().filter(sale_price__isnull=False, stock__gt=0).prefetch_related("images").order_by("-sold_count")[:4]
        out["products"] = [product_card(p) for p in sale]

    elif intent == "contact":
        out["reply"] = f"Hotline {biz['hotline']} (8:00–21:00), email {biz['email']}. Showroom: {biz['address']}."
        out["links"] = [{"text": "Gửi yêu cầu hỗ trợ", "url": reverse("pages:contact")}]

    elif intent == "recommend":
        products = find_products(e)
        parts = []
        if e["category"]:
            cat = Category.objects.filter(slug=e["category"]).first()
            parts.append(cat.name.lower() if cat else "gear")
        if e["tags"]:
            parts.append(", ".join(TAG_LABELS.get(t, t) for t in e["tags"]))
        if e["max"] and not e["min"]:
            parts.append(f"dưới {vnd(e['max'])}")
        elif e["min"] and e["max"]:
            parts.append(f"khoảng {vnd(e['min'])}–{vnd(e['max'])}")
        if e["brand"]:
            parts.append(e["brand"].name)
        if e["min"] and not e["max"]:
            parts.append(f"từ {vnd(e['min'])}")
        exact = products and all(t in products[0].tags for t in e["tags"])
        if products and not exact:
            # find_products() relaxed the tag filter — say so instead of over-promising
            wanted = ", ".join(TAG_LABELS.get(t, t) for t in e["tags"])
            parts = [p for p in parts if p != wanted]
            out["reply"] = f"Hiện chưa có mẫu {wanted} phù hợp. Bạn tham khảo {' '.join(parts) or 'sản phẩm'} bán chạy:"
            out["products"] = [product_card(p) for p in products]
            out["quick_replies"] = ["Đắt hơn chút", "Phí ship bao nhiêu?"]
            _save_context(request, e, products)
        elif products:
            out["reply"] = f"Gợi ý {' '.join(parts) or 'nổi bật'} đang bán chạy:"
            out["products"] = [product_card(p) for p in products]
            _save_context(request, e, products)
            out["quick_replies"] = ["Loại không dây thì sao?", "Rẻ hơn chút", "Phí ship bao nhiêu?"]
        else:
            out["reply"] = "Mình chưa tìm thấy sản phẩm khớp tiêu chí. Bạn thử nới ngân sách hoặc xem toàn bộ danh mục nhé."
            out["links"] = [{"text": "Xem tất cả sản phẩm", "url": reverse("catalog:list")}]

    if intent == "unknown":
        faq = _match_faq(e["norm"])
        if faq:
            out.update(intent="faq", reply=faq.answer)
        else:
            llm = _ask_llm(text, e) if settings.GEMINI_API_KEY else None
            if llm:
                out.update(intent="llm", reply=llm)
            else:
                out["reply"] = "Mình chưa hiểu câu hỏi lắm 😅 Bạn có thể hỏi về sản phẩm theo ngân sách, đơn hàng, phí ship, đổi trả, bảo hành hoặc khuyến mãi."
                out["quick_replies"] = ["Tai nghe dưới 2 triệu", "Chính sách đổi trả", "Gặp nhân viên"]
    return out


def _match_faq(norm):
    best, best_score = None, 0
    for f in FAQ.objects.filter(is_active=True):
        kws = [normalize(k).strip() for k in f.keywords.split(",") if k.strip()]
        score = sum(1 for k in kws if k and has(norm, k))
        if score > best_score:
            best, best_score = f, score
    return best


def _ask_llm(text, e):
    """Grounded LLM fallback (Gemini REST API, no SDK dependency). Returns None on any error."""
    products = find_products({**e, "category": e["category"]}, limit=5)
    context = "\n".join(f"- {p.name}: {vnd(p.current_price)}, {p.short_description}" for p in products)
    prompt = (
        "Bạn là trợ lý bán hàng của LevelUp Gear (cửa hàng gaming gear tại Việt Nam). Trả lời ngắn gọn bằng tiếng Việt, "
        "chỉ dựa trên thông tin sau; nếu không biết hãy đề nghị liên hệ hotline.\n"
        f"Chính sách: đổi trả 7 ngày nếu lỗi, freeship đơn từ {vnd(settings.FREE_SHIPPING_THRESHOLD)}, bảo hành chính hãng.\n"
        f"Sản phẩm liên quan:\n{context}\n\nCâu hỏi: {text}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        log.warning("LLM fallback failed", exc_info=True)
        return None
