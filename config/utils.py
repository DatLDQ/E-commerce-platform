import ipaddress

from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme


def _valid_ip(value):
    value = (value or "").strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def client_ip(request):
    """The visitor's IP address, trusting proxy headers only as far as settings allow (see settings.py)."""
    if settings.CLIENT_IP_HEADER:
        key = "HTTP_" + settings.CLIENT_IP_HEADER.upper().replace("-", "_")
        ip = _valid_ip(request.META.get(key))
        if ip:
            return ip
    if settings.TRUSTED_PROXY_COUNT > 0:
        hops = [h for h in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if h.strip()]
        if len(hops) >= settings.TRUSTED_PROXY_COUNT:
            ip = _valid_ip(hops[-settings.TRUSTED_PROXY_COUNT])
            if ip:
                return ip
    return _valid_ip(request.META.get("REMOTE_ADDR")) or ""


def safe_next(request, fallback):
    """Return the `next` parameter only if it points to this site (prevents open redirects)."""
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return fallback


def safe_referer(request, fallback):
    """Redirect back to the previous page, but only if it is on this site."""
    ref = request.META.get("HTTP_REFERER", "")
    if ref and url_has_allowed_host_and_scheme(ref, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return ref
    return fallback


def login_required_post(page):
    """Guard a POST-only action that needs a signed-in user.

    `page(request, *args, **kwargs)` returns the page the action belongs to (e.g. the product page).
    Anonymous visitors are sent to log in and then back to that page — never to the action URL itself,
    which only accepts POST and would answer 405 to the browser's GET after login. A stray GET on the
    action URL (an old bookmark or login link) also lands on the page instead of a 405.
    """
    from functools import wraps

    from django.contrib.auth.views import redirect_to_login
    from django.http import JsonResponse
    from django.shortcuts import redirect

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            target = page(request, *args, **kwargs)
            if request.method != "POST":
                return redirect(target)
            if not request.user.is_authenticated:
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"login_required": True}, status=401)
                return redirect_to_login(target)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def staff_required(view):
    """Dashboard guard. Unlike Django's staff_member_required, a signed-out visitor goes to the shop's
    login page — never to the admin login, whose URL is kept secret — and a signed-in customer gets 404."""
    from functools import wraps

    from django.contrib.auth.views import redirect_to_login
    from django.http import Http404
    from django.urls import reverse

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("accounts:login"))
        if not (request.user.is_active and request.user.is_staff):
            raise Http404
        return view(request, *args, **kwargs)

    return wrapped
