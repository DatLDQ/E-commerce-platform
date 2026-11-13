import json

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.recommendations import engine
from config.utils import client_ip, login_required_post, safe_next

from .forms import AddressForm, LoginForm, ProfileForm, RegisterForm
from .models import Address

MAX_LOGIN_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


def register(request):
    if request.user.is_authenticated:
        return redirect("pages:home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.data_consent_at = timezone.now()
        user.save()
        login(request, user, backend="apps.accounts.backends.EmailOrUsernameBackend")
        messages.success(request, f"Chào mừng {user.first_name} đến với LevelUp Gear! Nhập mã WELCOME10 để giảm 10% đơn đầu tiên.")
        return redirect(safe_next(request, "pages:home"))
    return render(request, "accounts/register.html", {"form": form})


class RateLimitedLoginView(auth_views.LoginView):
    """Login with brute-force protection: 5 failures per IP+username → 15-minute lockout."""

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def _key(self):
        ip = client_ip(self.request)
        user = self.request.POST.get("username", "").lower()[:100]
        return f"login-fail:{ip}:{user}"

    def post(self, request, *args, **kwargs):
        if cache.get(self._key(), 0) >= MAX_LOGIN_FAILURES:
            messages.error(request, "Bạn đã nhập sai quá nhiều lần. Vui lòng thử lại sau 15 phút.")
            return redirect("accounts:login")
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._key()
        cache.set(key, cache.get(key, 0) + 1, LOCKOUT_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._key())
        return super().form_valid(form)


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "Bạn đã đăng xuất.")
    return redirect("pages:home")


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã cập nhật hồ sơ.")
        return redirect("accounts:profile")
    return render(
        request,
        "accounts/profile.html",
        {"form": form, "recent_orders": request.user.orders.all()[:5], "recommended": engine.for_user(request, 4)},
    )


@login_required
def addresses(request):
    form = AddressForm(request.POST or None, initial={"full_name": request.user.get_full_name(), "phone": request.user.phone})
    if request.method == "POST" and form.is_valid():
        addr = form.save(commit=False)
        addr.user = request.user
        if not request.user.addresses.exists():
            addr.is_default = True
        addr.save()
        messages.success(request, "Đã thêm địa chỉ.")
        return redirect("accounts:addresses")
    return render(request, "accounts/addresses.html", {"form": form, "addresses": request.user.addresses.all()})


@login_required
def address_edit(request, pk):
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    form = AddressForm(request.POST or None, instance=addr)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã cập nhật địa chỉ.")
        return redirect("accounts:addresses")
    return render(request, "accounts/addresses.html", {"form": form, "addresses": request.user.addresses.all(), "editing": addr})


@login_required_post(lambda request, pk: reverse("accounts:addresses"))
def address_delete(request, pk):
    get_object_or_404(Address, pk=pk, user=request.user).delete()
    messages.info(request, "Đã xoá địa chỉ.")
    return redirect("accounts:addresses")


@login_required_post(lambda request, pk: reverse("accounts:addresses"))
def address_default(request, pk):
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    addr.is_default = True
    addr.save()
    return redirect("accounts:addresses")


@login_required
def privacy(request):
    return render(request, "accounts/privacy.html")


@login_required
def export_data(request):
    """Right of access (Personal Data Protection Law 2025): download all personal data as JSON."""
    u = request.user
    data = {
        "account": {
            "username": u.username,
            "full_name": u.get_full_name(),
            "email": u.email,
            "phone": u.phone,
            "gamer_tag": u.gamer_tag,
            "date_joined": u.date_joined.isoformat(),
            "marketing_opt_in": u.marketing_opt_in,
            "data_consent_at": u.data_consent_at.isoformat() if u.data_consent_at else None,
        },
        "addresses": [{"name": a.full_name, "phone": a.phone, "address": a.one_line()} for a in u.addresses.all()],
        "orders": [
            {
                "code": o.code,
                "created_at": o.created_at.isoformat(),
                "total": o.total,
                "status": o.status,
                "items": [{"name": i.product_name, "qty": i.quantity, "price": i.unit_price} for i in o.items.all()],
            }
            for o in u.orders.prefetch_related("items")
        ],
        "reviews": [{"product": r.product.name, "rating": r.rating, "comment": r.comment} for r in u.reviews.select_related("product")],
    }
    resp = HttpResponse(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="levelup-data-{u.username}.json"'
    return resp


@login_required_post(lambda request: reverse("accounts:privacy"))
def delete_account(request):
    """Right to erasure: anonymise the account (orders are kept for tax/accounting law)."""
    if request.POST.get("confirm") != "XOA":
        messages.error(request, "Vui lòng nhập XOA để xác nhận.")
        return redirect("accounts:privacy")
    u = request.user
    u.addresses.all().delete()
    u.orders.update(full_name="Đã ẩn danh", email=f"deleted-{u.pk}@invalid.local", phone="0000000000", street="—")
    u.username = f"deleted-{u.pk}"
    u.email = f"deleted-{u.pk}@invalid.local"
    u.first_name = u.last_name = u.phone = u.gamer_tag = ""
    u.is_active = False
    u.set_unusable_password()
    u.save()
    logout(request)
    messages.info(request, "Tài khoản đã được xoá và dữ liệu cá nhân đã được ẩn danh.")
    return redirect("pages:home")
