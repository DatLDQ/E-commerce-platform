from django.conf import settings
from django.utils import timezone

from .models import SiteVisit


class VisitTrackingMiddleware:
    """Records one SiteVisit per session per day (denominator of the conversion-rate KPI).

    Only real page views are counted: GET, HTML, not static/admin/API, not bots.
    """

    SKIP_PREFIXES = ("/static/", "/media/", "/" + settings.ADMIN_URL, "/quan-ly/", "/api/", "/chatbot/", "/favicon")
    BOT_HINTS = ("bot", "spider", "crawl", "headless")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._track(request, response)
        except Exception:
            pass
        return response

    def _track(self, request, response):
        if request.method != "GET" or response.status_code != 200 or request.path.startswith(self.SKIP_PREFIXES):
            return
        ua = request.META.get("HTTP_USER_AGENT", "").lower()
        if any(b in ua for b in self.BOT_HINTS):
            return
        today = timezone.localdate()
        if request.session.get("visit_day") == today.isoformat():
            return
        if not request.session.session_key:
            request.session.save()
        source = request.GET.get("utm_source", "")[:40] or ("referral" if request.META.get("HTTP_REFERER") else "direct")
        SiteVisit.objects.get_or_create(
            session_key=request.session.session_key,
            day=today,
            defaults={"user": request.user if request.user.is_authenticated else None, "source": source},
        )
        request.session["visit_day"] = today.isoformat()
