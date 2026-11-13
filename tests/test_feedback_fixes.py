"""Regression tests for issues found during manual testing of the deployed site."""
import urllib.parse

from django.contrib.messages import get_messages
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.cart.models import Cart
from apps.cart import services as cart_services
from apps.catalog.templatetags.shop import qty_max
from apps.orders.models import Coupon, Order
from apps.pages.models import NewsletterSubscriber, StoredFile
from apps.pages.storage import DatabaseStorage
from apps.payments import gateway

from .test_shop import BaseShopTest

DB_STORAGES = {
    "default": {"BACKEND": "apps.pages.storage.DatabaseStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _texts(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class NewsletterTests(BaseShopTest):
    def test_new_signup_shows_coupon_terms(self):
        Coupon.objects.create(code="WELCOME10", kind=Coupon.PERCENT, value=10, max_discount=200_000, first_order_only=True)
        r = self.client.post(reverse("pages:newsletter"), {"email": "new@example.com"})
        msg = " ".join(_texts(r))
        self.assertIn("thành công", msg)
        self.assertIn("WELCOME10", msg)
        self.assertIn("đăng nhập", msg)
        self.assertIn("200.000₫", msg)

    def test_duplicate_signup_is_reported(self):
        NewsletterSubscriber.objects.create(email="old@example.com")
        r = self.client.post(reverse("pages:newsletter"), {"email": "OLD@example.com"})
        msg = " ".join(_texts(r))
        self.assertIn("đã đăng ký", msg)
        self.assertNotIn("thành công", msg)
        self.assertEqual(NewsletterSubscriber.objects.count(), 1)


class QuantityCapTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.p1.stock = 80
        self.p1.save()

    def test_qty_max_filter(self):
        self.assertEqual(qty_max(self.p1), cart_services.MAX_QTY_PER_LINE)
        self.assertEqual(qty_max(self.m2), 3)

    def test_add_over_limit_warns(self):
        r = self.client.post(reverse("cart:add", args=[self.p1.pk]), {"quantity": 50}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        data = r.json()
        self.assertTrue(data["capped"])
        self.assertIn("tối đa 10", data["message"])
        self.assertEqual(data["cart_count"], 10)

    def test_add_over_stock_warns(self):
        r = self.client.post(reverse("cart:add", args=[self.m2.pk]), {"quantity": 9}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertIn("Chỉ còn 3", r.json()["message"])

    def test_update_over_limit_warns(self):
        self.add(self.p1)
        r = self.client.post(reverse("cart:update", args=[self.p1.pk]), {"quantity": 50}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.json()["quantity"], 10)
        self.assertIn("tối đa 10", r.json()["message"])

    def test_cart_input_max_matches_limit(self):
        self.add(self.p1)
        self.assertContains(self.client.get(reverse("cart:detail")), 'max="10"')


class SummaryTests(BaseShopTest):
    def test_item_count_same_in_cart_and_checkout(self):
        self.add(self.p1, 3)
        self.add(self.m1, 2)
        self.assertContains(self.client.get(reverse("cart:detail")), "5</span> sản phẩm")
        self.assertContains(self.client.get(reverse("orders:checkout")), "5 sản phẩm")

    def test_freeship_has_no_zero_discount_line(self):
        Coupon.objects.create(code="FREESHIP", kind=Coupon.FREESHIP, min_order=0)
        self.add(self.p1)
        self.client.post(reverse("cart:coupon"), {"code": "FREESHIP"})
        html = self.client.get(reverse("orders:checkout")).content.decode()
        self.assertNotIn("−0₫", html)
        self.assertIn("(mã FREESHIP)", html)


@override_settings(PAYMENT_MODE="mock", SITE_URL="http://testserver")
class InvalidTransactionTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.add(self.p1)
        self.checkout(payment_method="vnpay")
        self.order = Order.objects.get()
        r = self.client.post(reverse("payments:start", args=[self.order.code]))
        url = urllib.parse.urlparse(r.url)
        self.path, self.params = url.path, dict(urllib.parse.parse_qsl(url.query))

    def test_tampered_return_url_shows_error_page(self):
        result = gateway.mock_result_params(self.params, "success")
        result["vnp_Amount"] = "100"
        r = self.client.get(reverse("payments:return"), result)
        self.assertEqual(r.status_code, 400)
        self.assertContains(r, "Giao dịch không hợp lệ", status_code=400)

    def test_tampered_gateway_request_shows_error_page(self):
        self.params["vnp_Amount"] = "1000"
        r = self.client.get(self.path, self.params)
        self.assertContains(r, "Giao dịch không hợp lệ", status_code=400)


class SiteChromeTests(BaseShopTest):
    def test_favicon(self):
        r = self.client.get("/favicon.ico")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/x-icon")

    def test_admin_not_at_default_path(self):
        self.assertEqual(self.client.get("/admin/").status_code, 404)
        self.assertNotEqual(reverse("admin:index"), "/admin/")
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)  # to admin login


@override_settings(STORAGES=DB_STORAGES)
class DatabaseStorageTests(BaseShopTest):
    def test_roundtrip_and_serving(self):
        storage = storages["default"]
        self.assertIsInstance(storage, DatabaseStorage)
        name = storage.save("products/a.png", ContentFile(b"\x89PNG-data"))
        self.assertTrue(storage.exists(name))
        self.assertEqual(storage.size(name), 9)
        with storage.open(name) as f:
            self.assertEqual(f.read(), b"\x89PNG-data")
        r = self.client.get(storage.url(name))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertEqual(r.content, b"\x89PNG-data")
        self.assertEqual(self.client.get(storage.url(name), HTTP_IF_NONE_MATCH=r["ETag"]).status_code, 304)
        storage.delete(name)
        self.assertFalse(StoredFile.objects.filter(name=name).exists())
        self.assertEqual(self.client.get(storage.url(name)).status_code, 404)

    def test_name_collision_gets_new_name(self):
        storage = storages["default"]
        a = storage.save("x.txt", ContentFile(b"1"))
        b = storage.save("x.txt", ContentFile(b"2"))
        self.assertNotEqual(a, b)


class PostOnlyLoginRedirectTests(BaseShopTest):
    def test_wishlist_get_goes_to_product(self):
        r = self.client.get(reverse("catalog:toggle_wishlist", args=[self.p1.pk]))
        self.assertRedirects(r, self.p1.get_absolute_url(), fetch_redirect_response=False)

    def test_anonymous_post_next_is_product_page(self):
        r = self.client.post(reverse("catalog:toggle_wishlist", args=[self.p1.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=" + urllib.parse.quote(self.p1.get_absolute_url()), r.url)

    def test_anonymous_xhr_gets_401(self):
        r = self.client.post(reverse("catalog:toggle_wishlist", args=[self.p1.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 401)

    def test_logged_in_post_works(self):
        User.objects.create_user("w1", "w1@example.com", "Passw0rd!x")
        self.client.login(username="w1", password="Passw0rd!x")
        r = self.client.post(reverse("catalog:toggle_wishlist", args=[self.p1.pk]))
        self.assertEqual(r.status_code, 302)


class StaleCouponTests(BaseShopTest):
    """A coupon that stops qualifying (cart went under its minimum) must not block checkout."""

    def setUp(self):
        super().setUp()
        Coupon.objects.create(code="BIG15", kind=Coupon.PERCENT, value=15, max_discount=500_000, min_order=2_000_000)
        self.m2.stock = 10
        self.m2.save()
        self.add(self.p1)  # 600.000₫
        self.add(self.m2)  # + 3.000.000₫
        self.client.post(reverse("cart:coupon"), {"code": "BIG15"})
        self.client.post(reverse("cart:remove", args=[self.m2.pk]))  # back under the 2.000.000₫ minimum
        list(get_messages(self.client.get("/").wsgi_request))  # flush earlier notices

    def test_cart_page_drops_coupon_with_reason(self):
        r = self.client.get(reverse("cart:detail"))
        self.assertIn("Đã gỡ mã BIG15", " ".join(_texts(r)))
        self.assertEqual(Cart.objects.get().coupon_code, "")

    def test_checkout_goes_through_after_coupon_dropped(self):
        r = self.checkout()
        self.assertEqual(r.status_code, 200)  # form shown again with the warning, nothing placed yet
        self.assertIn("Đã gỡ mã BIG15", " ".join(_texts(r)))
        self.assertFalse(Order.objects.exists())
        r = self.checkout()
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Order.objects.get().discount, 0)

    def test_ajax_update_asks_for_reload(self):
        Cart.objects.update(coupon_code="BIG15")
        r = self.client.post(reverse("cart:update", args=[self.p1.pk]), {"quantity": 2}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(r.json()["reload"])
        self.assertEqual(Cart.objects.get().coupon_code, "")


class HomePageTests(BaseShopTest):
    def test_single_h1_with_carousel(self):
        from apps.pages.models import Banner

        for i in range(3):
            Banner.objects.create(title=f"Banner {i}", subtitle="x", cta_url="/", cta_text="Xem", theme="violet", sort_order=i)
        html = self.client.get("/").content.decode()
        self.assertEqual(html.count("<h1"), 1)
