from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.files.storage import storages
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.views.static import serve as static_serve

from apps.catalog.models import Category, Product
from apps.chatbot.models import FAQ
from apps.orders.models import Coupon
from apps.recommendations import engine
from config.utils import safe_next

from .models import Banner, ContactMessage, NewsletterSubscriber, StoredFile
from .storage import DatabaseStorage
from .storage import content_type as media_content_type

POLICIES = {
    "dieu-khoan": "Điều khoản sử dụng & mua hàng",
    "bao-mat": "Chính sách bảo mật dữ liệu cá nhân",
    "doi-tra": "Chính sách đổi trả & hoàn tiền",
    "van-chuyen": "Chính sách vận chuyển & giao nhận",
    "bao-hanh": "Chính sách bảo hành",
    "thanh-toan": "Chính sách thanh toán",
    "giai-quyet-khieu-nai": "Cơ chế giải quyết khiếu nại",
}


def home(request):
    products = Product.objects.active().select_related("brand").prefetch_related("images").with_ratings()
    return render(
        request,
        "pages/home.html",
        {
            "banners": Banner.objects.filter(is_active=True),
            "categories": Category.objects.annotate(n_products=Count("products", filter=Q(products__is_active=True))),
            "flash_sale": products.filter(sale_price__isnull=False, stock__gt=0).order_by("-sold_count")[:8],
            "featured": products.filter(is_featured=True)[:8],
            "for_you": engine.for_user(request, 8),
            "new_arrivals": products.order_by("-created_at")[:8],
            "recently_viewed": engine.recently_viewed(request, 6),
        },
    )


def about(request):
    return render(request, "pages/about.html")


def photo_credits(request):
    """Attribution for the openly-licensed photos (CC BY / CC BY-SA require it)."""
    from apps.catalog.management.commands.seed_demo import photo_credits as load

    credits = sorted(load().values(), key=lambda c: (c.get("group", ""), c.get("used_for", "")))
    return render(request, "pages/credits.html", {"credits": credits})


def policy(request, slug):
    if slug not in POLICIES:
        raise Http404
    return render(request, f"pages/policies/{slug}.html", {"title": POLICIES[slug], "policies": POLICIES, "slug": slug})


class ContactForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # honeypot against spam bots

    class Meta:
        model = ContactMessage
        fields = ["name", "email", "subject", "message"]
        labels = {"name": "Họ tên", "subject": "Chủ đề", "message": "Nội dung"}


def contact(request):
    initial = {"subject": request.GET.get("subject", "")[:150]}
    if request.user.is_authenticated:
        initial.update(name=request.user.get_full_name(), email=request.user.email)
    form = ContactForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        if not form.cleaned_data.get("website"):
            form.save()
        messages.success(request, "Cảm ơn bạn! Chúng tôi sẽ phản hồi trong vòng 24 giờ làm việc.")
        return redirect("pages:contact")
    return render(request, "pages/contact.html", {"form": form})


def faq(request):
    return render(request, "pages/faq.html", {"faqs": FAQ.objects.filter(is_active=True)})


@require_POST
def newsletter(request):
    email = request.POST.get("email", "").strip().lower()
    try:
        forms.EmailField().clean(email)
        _, created = NewsletterSubscriber.objects.get_or_create(email=email)
        if not created:
            messages.info(request, "Email này đã đăng ký nhận tin trước đó — bạn không cần đăng ký lại.")
        else:
            welcome = Coupon.objects.filter(code="WELCOME10", is_active=True).first()
            offer = f" Ưu đãi cho bạn: mã {welcome.code} — {welcome.terms()}." if welcome else ""
            messages.success(request, "Đăng ký nhận tin thành công!" + offer)
    except forms.ValidationError:
        messages.error(request, "Email không hợp lệ.")
    return redirect(safe_next(request, "pages:home"))


def robots(request):
    lines = ["User-agent: *", "Disallow: /quan-ly/", "Disallow: /gio-hang/", "Disallow: /don-hang/", f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}"]
    return HttpResponse("\n".join(lines), content_type="text/plain")


_FAVICON = settings.BASE_DIR / "static" / "favicon.ico"


def favicon(request):
    """Browsers ask for /favicon.ico on their own, whatever the page's <link rel=icon> says."""
    try:
        data = _FAVICON.read_bytes()
    except OSError:
        raise Http404
    response = HttpResponse(data, content_type="image/x-icon")
    response["Cache-Control"] = "public, max-age=604800"
    return response


def serve_media(request, path):
    """Uploaded files: from the database when DatabaseStorage is in use, otherwise from MEDIA_ROOT."""
    if not isinstance(storages["default"], DatabaseStorage):
        return static_serve(request, path, document_root=settings.MEDIA_ROOT)
    row = StoredFile.objects.filter(name=path).only("content", "size", "created_at").first()
    if row is None:
        raise Http404
    etag = f'"{row.size}-{int(row.created_at.timestamp())}"'
    if request.headers.get("If-None-Match") == etag:
        return HttpResponseNotModified()
    response = HttpResponse(bytes(row.content), content_type=media_content_type(path))
    response["ETag"] = etag
    response["Cache-Control"] = "public, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    return response
