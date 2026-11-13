from django.conf import settings


def site(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "BUSINESS": settings.BUSINESS_INFO,
        "FREE_SHIP": settings.FREE_SHIPPING_THRESHOLD,
        "cookie_consent": request.COOKIES.get("cookie_consent"),
    }
