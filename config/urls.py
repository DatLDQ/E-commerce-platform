from django.conf import settings
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path, re_path

from apps.pages.sitemaps import CategorySitemap, ProductSitemap, StaticSitemap
from apps.pages.views import favicon, robots, serve_media

sitemaps = {"products": ProductSitemap, "categories": CategorySitemap, "static": StaticSitemap}

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("quan-ly/", include("apps.dashboard.urls")),
    path("san-pham/", include("apps.catalog.urls")),
    path("gio-hang/", include("apps.cart.urls")),
    path("don-hang/", include("apps.orders.urls")),
    path("thanh-toan-online/", include("apps.payments.urls")),
    path("tai-khoan/", include("apps.accounts.urls")),
    path("chatbot/", include("apps.chatbot.urls")),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("robots.txt", robots),
    path("favicon.ico", favicon),
    path("", include("apps.pages.urls")),
]

if settings.SERVE_MEDIA:
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve_media)]

handler404 = "apps.pages.errors.not_found"
handler500 = "apps.pages.errors.server_error"
