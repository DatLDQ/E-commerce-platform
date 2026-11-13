"""Customer account flows and dashboard safeguards."""
import csv
import io
from datetime import timedelta

from django.contrib.messages import get_messages
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Address, User
from apps.cart.models import Cart
from apps.catalog.models import Review, Wishlist
from apps.dashboard import analytics
from apps.orders.models import Order
from config.utils import client_ip

from .test_shop import CHECKOUT, BaseShopTest

PASSWORD = "Passw0rd!x"


def _texts(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class CustomerTest(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("khach", "khach@example.com", PASSWORD, first_name="An", last_name="Nguyễn")
        self.client.login(username="khach", password=PASSWORD)

    def place(self, **overrides):
        self.add(self.p1)
        self.checkout(**overrides)
        return Order.objects.latest("id")


class TaxCodeTests(CustomerTest):
    def vat(self, code):
        self.add(self.p1)
        return self.checkout(want_vat_invoice="on", vat_company="Công ty ABC", vat_tax_code=code)

    def test_rejects_malformed_codes(self):
        for code in ["123", "abcdefghij", "01234567890", "0123456789-12", "0123456789-1234"]:
            r = self.vat(code)
            self.assertEqual(r.status_code, 200, code)
            self.assertContains(r, "Mã số thuế gồm 10 chữ số")
        self.assertFalse(Order.objects.exists())

    def test_accepts_10_and_13_digit_codes(self):
        for code in ["0123456789", "0123456789-001", "0123456789001"]:
            self.vat(code)
        self.assertEqual(Order.objects.count(), 3)


class CancelTests(CustomerTest):
    def test_second_cancel_says_already_cancelled(self):
        order = self.place()
        url = reverse("orders:cancel", args=[order.code])
        self.client.post(url, {"reason": "Đặt nhầm"})
        r = self.client.post(url, {"reason": "Đặt nhầm"}, follow=True)
        html = r.content.decode()
        self.assertIn("đã được huỷ trước đó", html)
        self.assertNotIn("không thể huỷ", html)

    def test_duplicate_notices_shown_once(self):
        order = self.place()
        self.client.post(reverse("orders:cancel", args=[order.code]))
        url = reverse("orders:cancel", args=[order.code])
        self.client.post(url)
        r = self.client.post(url, follow=True)
        self.assertEqual(r.content.decode().count("đã được huỷ trước đó"), 1)


class OwnerLinkTests(CustomerTest):
    def test_my_orders_links_have_no_token(self):
        order = self.place()
        html = self.client.get(reverse("orders:mine")).content.decode()
        self.assertIn(reverse("orders:detail", args=[order.code]) + '"', html)
        self.assertNotIn(order.access_token, html)

    def test_owner_detail_and_cancel_without_token(self):
        order = self.place()
        r = self.client.get(reverse("orders:detail", args=[order.code]))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("?t=" + order.access_token, r.content.decode())
        r = self.client.post(reverse("orders:cancel", args=[order.code]))
        self.assertRedirects(r, reverse("orders:detail", args=[order.code]), fetch_redirect_response=False)

    def test_stranger_still_needs_token(self):
        order = self.place()
        self.client.logout()
        self.assertEqual(self.client.get(reverse("orders:detail", args=[order.code])).status_code, 404)
        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 200)


class AddressEditTests(CustomerTest):
    def test_edit_own_address(self):
        a = Address.objects.create(user=self.user, full_name="An", phone="0901234567", province="TP. Hồ Chí Minh", ward="Phường Bến Thành", street="1 Lê Lợi", is_default=True)
        url = reverse("accounts:address_edit", args=[a.pk])
        self.assertContains(self.client.get(url), "Lưu thay đổi")
        r = self.client.post(url, {"full_name": "An Nguyễn", "phone": "0901234567", "province": "TP. Hồ Chí Minh", "ward": "Phường Sài Gòn", "street": "99 Hai Bà Trưng", "is_default": "on"})
        self.assertRedirects(r, reverse("accounts:addresses"), fetch_redirect_response=False)
        a.refresh_from_db()
        self.assertEqual((a.full_name, a.street, a.ward), ("An Nguyễn", "99 Hai Bà Trưng", "Phường Sài Gòn"))

    def test_cannot_edit_someone_elses_address(self):
        other = User.objects.create_user("khac", "khac@example.com", PASSWORD)
        a = Address.objects.create(user=other, full_name="B", phone="0901234567", province="Hà Nội", ward="x", street="y")
        self.assertEqual(self.client.get(reverse("accounts:address_edit", args=[a.pk])).status_code, 404)


class WishlistCompareTests(CustomerTest):
    def test_wishlist_page_has_remove_button(self):
        Wishlist.objects.create(user=self.user, product=self.p1)
        r = self.client.get(reverse("catalog:wishlist"))
        self.assertContains(r, "Bỏ khỏi yêu thích")
        self.client.post(reverse("catalog:toggle_wishlist", args=[self.p1.pk]), {"next": reverse("catalog:wishlist")})
        self.assertFalse(Wishlist.objects.exists())

    def test_compare_page_has_remove_links(self):
        ids = f"{self.p1.pk},{self.m1.pk}"
        r = self.client.get(reverse("catalog:compare"), {"ids": ids})
        self.assertContains(r, "Bỏ khỏi so sánh", count=2)
        self.assertContains(r, f'href="?ids={self.m1.pk}"')
        self.assertContains(r, f'href="?ids={self.p1.pk}"')


class BuyAgainReviewTests(CustomerTest):
    def deliver(self, order):
        Order.objects.filter(pk=order.pk).update(status=Order.Status.DELIVERED)
        order.refresh_from_db()
        return order

    def test_buy_again_refills_cart(self):
        order = self.deliver(self.place())
        Cart.objects.all().delete()
        r = self.client.post(reverse("orders:buy_again", args=[order.code]))
        self.assertRedirects(r, reverse("cart:detail"), fetch_redirect_response=False)
        self.assertEqual(Cart.objects.get().items.get().product, self.p1)

    def test_buy_again_skips_inactive_products(self):
        order = self.deliver(self.place())
        Cart.objects.all().delete()
        self.p1.is_active = False
        self.p1.save()
        r = self.client.post(reverse("orders:buy_again", args=[order.code]))
        self.assertIn("Không thể thêm", " ".join(_texts(r)))

    def test_delivered_order_offers_review_and_return(self):
        order = self.deliver(self.place())
        r = self.client.get(reverse("orders:detail", args=[order.code]))
        self.assertContains(r, "Mua lại")
        self.assertContains(r, "Viết đánh giá")
        self.assertContains(r, "Yêu cầu đổi trả")
        Review.objects.create(product=self.p1, user=self.user, rating=5, title="Tốt", comment="Rất tốt")
        self.assertContains(self.client.get(reverse("orders:detail", args=[order.code])), "Đã đánh giá")

    def test_pending_order_has_no_review_link(self):
        order = self.place()
        self.assertNotContains(self.client.get(reverse("orders:detail", args=[order.code])), "Viết đánh giá")


# ---------------------------------------------------------------- dashboard
class StaffTest(BaseShopTest):
    def setUp(self):
        super().setUp()
        User.objects.create_superuser("boss", "boss@example.com", PASSWORD)
        self.client.login(username="boss", password=PASSWORD)


class StockAdjustTests(StaffTest):
    def adjust(self, delta):
        r = self.client.post(reverse("dashboard:product_stock", args=[self.m2.pk]), {"delta": delta})
        self.m2.refresh_from_db()
        return " ".join(_texts(r))

    def test_not_a_number(self):
        self.assertIn("không phải số nguyên", self.adjust("abc"))
        self.assertEqual(self.m2.stock, 3)

    def test_cannot_go_below_zero(self):
        self.assertIn("chỉ còn 3", self.adjust("-999"))
        self.assertEqual(self.m2.stock, 3)

    def test_valid_adjustments(self):
        self.adjust("5")
        self.assertEqual(self.m2.stock, 8)
        self.assertIn("8 → 0", self.adjust("-8"))
        self.assertEqual(self.m2.stock, 0)


class OrderStatusAdminTests(StaffTest):
    def setUp(self):
        super().setUp()
        self.add(self.p1)
        self.checkout()
        self.order = Order.objects.get()
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.PACKING)
        self.url = reverse("dashboard:order_detail", args=[self.order.code])

    def test_invalid_status_message_is_generic(self):
        r = self.client.post(self.url, {"action": "status", "status": "xyz"}, follow=True)
        html = r.content.decode()
        self.assertIn("Trạng thái không hợp lệ", html)
        self.assertNotIn("is not a valid", html)

    def test_shipping_needs_tracking(self):
        r = self.client.post(self.url, {"action": "status", "status": "shipping"}, follow=True)
        self.assertContains(r, "mã vận đơn")
        self.assertEqual(Order.objects.get().status, Order.Status.PACKING)
        self.client.post(self.url, {"action": "tracking", "carrier": "GHN", "tracking_number": "GHN123"})
        self.client.post(self.url, {"action": "status", "status": "shipping"})
        self.assertEqual(Order.objects.get().status, Order.Status.SHIPPING)

    def test_pickup_ships_without_tracking(self):
        Order.objects.filter(pk=self.order.pk).update(delivery_method=self.pick)
        self.client.post(self.url, {"action": "status", "status": "shipping"})
        self.assertEqual(Order.objects.get().status, Order.Status.SHIPPING)

    def test_csv_starts_with_bom(self):
        r = self.client.get(reverse("dashboard:orders"), {"export": "csv"})
        self.assertTrue(r.content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0][0], "Mã đơn")
        self.assertEqual(rows[1][0], self.order.code)


class DashboardAccessTests(BaseShopTest):
    def test_logged_out_goes_to_shop_login(self):
        r = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.startswith(reverse("accounts:login")), r.url)
        self.assertNotIn(reverse("admin:index"), r.url)


class CustomerPageTests(StaffTest):
    def setUp(self):
        super().setUp()
        self.buyers = []
        for i in range(30):
            u = User.objects.create_user(f"kh{i}", f"kh{i}@example.com", PASSWORD, first_name=f"Tên{i}", last_name="Trần", phone=f"0900000{i:03d}")
            Order.objects.create(user=u, full_name=u.first_name, email=u.email, phone=u.phone, province="Hà Nội", ward="x", street="y", delivery_method=self.std, subtotal=1_000_000 * (i + 1), total=1_000_000 * (i + 1), status=Order.Status.COMPLETED)
            self.buyers.append(u)

    def test_paginated(self):
        r = self.client.get(reverse("dashboard:customers"))
        self.assertEqual(len(r.context["page"]), 25)
        self.assertEqual(r.context["page"].paginator.count, 30)
        self.assertEqual(len(self.client.get(reverse("dashboard:customers"), {"page": 2}).context["page"]), 5)

    def test_search(self):
        for q in ["kh7@example.com", "0900000007", "tên7 "]:
            rows = list(self.client.get(reverse("dashboard:customers"), {"q": q}).context["page"])
            self.assertEqual([r["user_id"] for r in rows], [self.buyers[7].pk], q)

    def test_detail_page(self):
        u = self.buyers[3]
        r = self.client.get(reverse("dashboard:customer_detail", args=[u.pk]))
        self.assertContains(r, u.email)
        self.assertContains(r, u.orders.get().code)

    def test_vip_is_a_minority(self):
        segs = [r["segment"] for r in analytics.customer_segments()]
        self.assertLessEqual(segs.count("VIP"), len(segs) * 0.25)


class AovTests(BaseShopTest):
    def test_aov_is_rounded(self):
        for total in (100_000, 100_000, 100_001, 100_001):
            Order.objects.create(full_name="x", email="x@example.com", phone="0901234567", province="Hà Nội", ward="x", street="y", delivery_method=self.std, subtotal=total, total=total, status=Order.Status.COMPLETED)
        Order.objects.update(created_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(analytics.kpis()["aov"], 100_001)  # 400.002 / 4 = 100.000,5


class ClientIpTests(BaseShopTest):
    def req(self, xff="", remote="10.0.0.5", **headers):
        meta = {"REMOTE_ADDR": remote, **headers}
        if xff:
            meta["HTTP_X_FORWARDED_FOR"] = xff
        return RequestFactory().get("/", **meta)

    @override_settings(CLIENT_IP_HEADER="", TRUSTED_PROXY_COUNT=0)
    def test_no_proxy_ignores_headers(self):
        self.assertEqual(client_ip(self.req("1.2.3.4")), "10.0.0.5")

    @override_settings(CLIENT_IP_HEADER="", TRUSTED_PROXY_COUNT=1)
    def test_forged_left_hops_ignored(self):
        self.assertEqual(client_ip(self.req("6.6.6.6, 203.0.113.9")), "203.0.113.9")
        self.assertEqual(client_ip(self.req("203.0.113.9")), "203.0.113.9")
        self.assertEqual(client_ip(self.req("not-an-ip")), "10.0.0.5")
        self.assertEqual(client_ip(self.req()), "10.0.0.5")

    @override_settings(CLIENT_IP_HEADER="CF-Connecting-IP", TRUSTED_PROXY_COUNT=1)
    def test_edge_header_wins(self):
        self.assertEqual(client_ip(self.req("6.6.6.6, 172.70.1.1", HTTP_CF_CONNECTING_IP="198.51.100.7")), "198.51.100.7")
        self.assertEqual(client_ip(self.req("6.6.6.6, 203.0.113.9", HTTP_CF_CONNECTING_IP="garbage")), "203.0.113.9")

    @override_settings(CLIENT_IP_HEADER="", TRUSTED_PROXY_COUNT=1)
    def test_order_records_forwarded_ip(self):
        self.add(self.p1)
        self.client.post(reverse("orders:checkout"), {**CHECKOUT, "delivery_method": self.std.pk}, HTTP_X_FORWARDED_FOR="203.0.113.9")
        self.assertEqual(Order.objects.get().ip_address, "203.0.113.9")
