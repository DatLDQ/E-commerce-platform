"""End-to-end and unit tests for LevelUp Gear.

Run:  python manage.py test
"""
import json
import urllib.parse

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.cart.models import Cart
from apps.catalog.models import Brand, Category, Product
from apps.chatbot.engine import detect_intent, extract, parse_budget
from apps.orders import services
from apps.orders.models import Coupon, DeliveryMethod, Order
from apps.payments import gateway
from apps.payments.models import Payment
from apps.recommendations import engine


def make_catalogue():
    mouse = Category.objects.create(name="Chuột gaming", slug="chuot", icon="mouse")
    pad = Category.objects.create(name="Lót chuột", slug="lot-chuot", icon="pad")
    brand = Brand.objects.create(name="Logitech G")
    m1 = Product.objects.create(category=mouse, brand=brand, name="Logitech G304", sku="M1", price=900_000, sale_price=750_000, stock=5, tags="wireless,fps,budget", weight_grams=200)
    m2 = Product.objects.create(category=mouse, brand=brand, name="Logitech G Pro Superlight", sku="M2", price=3_000_000, stock=3, tags="wireless,fps", weight_grams=200)
    p1 = Product.objects.create(category=pad, brand=brand, name="Logitech G640 Bàn di", sku="P1", price=600_000, stock=10, tags="moba", weight_grams=600)
    return m1, m2, p1


def make_methods():
    std = DeliveryMethod.objects.create(code="standard", name="Tiêu chuẩn", base_fee=30_000, fee_per_extra_kg=5_000, outer_region_surcharge=10_000)
    exp = DeliveryMethod.objects.create(code="express", name="2H", base_fee=45_000, only_provinces="TP. Hồ Chí Minh, Hà Nội", free_ship_eligible=False, outer_region_surcharge=0)
    pick = DeliveryMethod.objects.create(code="pickup", name="Tại cửa hàng", base_fee=0, is_pickup=True, only_provinces="TP. Hồ Chí Minh")
    return std, exp, pick


CHECKOUT = {
    "full_name": "Nguyễn Văn A", "email": "a@example.com", "phone": "0901234567", "province": "TP. Hồ Chí Minh",
    "ward": "Phường Diên Hồng", "street": "268 Lý Thường Kiệt", "payment_method": "cod", "agree_terms": "on",
}


class BaseShopTest(TestCase):
    def setUp(self):
        cache.clear()
        self.m1, self.m2, self.p1 = make_catalogue()
        self.std, self.exp, self.pick = make_methods()

    def add(self, product, qty=1, client=None):
        return (client or self.client).post(reverse("cart:add", args=[product.pk]), {"quantity": qty})

    def checkout(self, **overrides):
        data = {**CHECKOUT, "delivery_method": self.std.pk, **overrides}
        return self.client.post(reverse("orders:checkout"), data)


# ---------------------------------------------------------------- pricing
class ShippingFeeTests(BaseShopTest):
    def test_inner_city_base_fee(self):
        self.assertEqual(services.shipping_fee(self.std, "TP. Hồ Chí Minh", 500_000, 1000), 30_000)

    def test_outer_region_surcharge_and_extra_weight(self):
        # 4.5 kg -> 3 extra kg over the 2 kg allowance
        self.assertEqual(services.shipping_fee(self.std, "Cần Thơ", 500_000, 4500), 30_000 + 3 * 5_000 + 10_000)

    def test_free_shipping_threshold(self):
        self.assertEqual(services.shipping_fee(self.std, "Hà Nội", 1_000_000, 1000), 0)

    def test_express_not_free_shipping_eligible(self):
        self.assertEqual(services.shipping_fee(self.exp, "TP. Hồ Chí Minh", 5_000_000, 1000), 45_000)

    def test_pickup_is_free(self):
        self.assertEqual(services.shipping_fee(self.pick, "TP. Hồ Chí Minh", 100_000, 1000), 0)

    def test_freeship_coupon(self):
        c = Coupon.objects.create(code="FS", kind=Coupon.FREESHIP, min_order=0)
        self.assertEqual(services.shipping_fee(self.std, "Cần Thơ", 200_000, 1000, c), 0)


class CouponTests(BaseShopTest):
    def test_percent_with_cap(self):
        c = Coupon.objects.create(code="P10", kind=Coupon.PERCENT, value=10, max_discount=100_000)
        self.assertEqual(c.discount_for(500_000), 50_000)
        self.assertEqual(c.discount_for(5_000_000), 100_000)

    def test_min_order(self):
        c = Coupon.objects.create(code="F50", kind=Coupon.FIXED, value=50_000, min_order=800_000)
        self.assertFalse(c.validate(700_000)[0])
        self.assertTrue(c.validate(800_000)[0])

    def test_usage_limit(self):
        c = Coupon.objects.create(code="ONE", kind=Coupon.FIXED, value=10_000, usage_limit=1, used_count=1)
        self.assertFalse(c.validate(1_000_000)[0])

    def test_first_order_only(self):
        u = User.objects.create_user("u1", "u1@x.com", "Passw0rd!x")
        c = Coupon.objects.create(code="WELCOME", kind=Coupon.PERCENT, value=10, first_order_only=True)
        self.assertTrue(c.validate(500_000, u)[0])
        Order.objects.create(user=u, full_name="x", email="x@x.com", phone="0900000000", province="Hà Nội", district="x", street="x",
                             delivery_method=self.std, subtotal=1, total=1, payment_method="cod")
        self.assertFalse(c.validate(500_000, u)[0])


# ---------------------------------------------------------------- cart
class CartTests(BaseShopTest):
    def test_add_is_capped_by_stock(self):
        self.add(self.m1, 99)
        cart = Cart.objects.get()
        self.assertEqual(cart.items.get().quantity, 5)

    def test_cart_uses_server_price_not_client(self):
        self.client.post(reverse("cart:add", args=[self.m1.pk]), {"quantity": 1, "price": 1})
        self.assertEqual(Cart.objects.get().subtotal, 750_000)

    def test_ajax_add_returns_count(self):
        r = self.client.post(reverse("cart:add", args=[self.p1.pk]), {"quantity": 2}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.json()["cart_count"], 2)

    def test_update_and_remove(self):
        self.add(self.p1, 2)
        self.client.post(reverse("cart:update", args=[self.p1.pk]), {"quantity": 4})
        self.assertEqual(Cart.objects.get().items.get().quantity, 4)
        self.client.post(reverse("cart:remove", args=[self.p1.pk]))
        self.assertFalse(Cart.objects.get().items.exists())

    def test_guest_cart_merges_on_login(self):
        User.objects.create_user("gamer", "g@x.com", "Passw0rd!x")
        self.add(self.p1, 2)
        self.client.post(reverse("accounts:login"), {"username": "gamer", "password": "Passw0rd!x"})
        user_cart = Cart.objects.get(user__username="gamer")
        self.assertEqual(user_cart.items.get().quantity, 2)

    def test_open_redirect_blocked(self):
        r = self.client.post(reverse("cart:add", args=[self.p1.pk]), {"quantity": 1, "next": "https://evil.example.com/"})
        self.assertEqual(r.url, reverse("cart:detail"))

    def test_apply_coupon(self):
        Coupon.objects.create(code="GAMER50K", kind=Coupon.FIXED, value=50_000, min_order=0)
        self.add(self.p1)
        self.client.post(reverse("cart:coupon"), {"code": "gamer50k"})
        self.assertEqual(Cart.objects.get().coupon_code, "GAMER50K")


# ---------------------------------------------------------------- checkout
class CheckoutTests(BaseShopTest):
    def test_cod_checkout_creates_order_and_decrements_stock(self):
        self.add(self.m1, 2)
        self.add(self.p1, 1)
        r = self.checkout()
        order = Order.objects.get()
        self.assertRedirects(r, reverse("orders:success", args=[order.code]))
        self.assertEqual(order.subtotal, 2 * 750_000 + 600_000)
        self.assertEqual(order.shipping_fee, 0)  # above free-ship threshold
        self.assertEqual(order.total, 2_100_000)
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.stock, 3)
        self.assertEqual(self.m1.sold_count, 2)
        self.assertFalse(Cart.objects.get().items.exists())
        self.assertEqual(order.history.count(), 1)

    def test_out_of_stock_is_rejected(self):
        self.add(self.m2, 3)
        Product.objects.filter(pk=self.m2.pk).update(stock=1)
        self.checkout()
        self.assertFalse(Order.objects.exists())

    def test_terms_must_be_accepted(self):
        self.add(self.p1)
        data = {**CHECKOUT, "delivery_method": self.std.pk}
        data.pop("agree_terms")
        self.client.post(reverse("orders:checkout"), data)
        self.assertFalse(Order.objects.exists())

    def test_express_not_available_outside_big_cities(self):
        self.add(self.p1)
        self.checkout(delivery_method=self.exp.pk, province="Cần Thơ")
        self.assertFalse(Order.objects.exists())

    def test_coupon_applied_in_order(self):
        Coupon.objects.create(code="F50", kind=Coupon.FIXED, value=50_000)
        self.add(self.p1)
        self.client.post(reverse("cart:coupon"), {"code": "F50"})
        self.checkout()
        o = Order.objects.get()
        self.assertEqual(o.discount, 50_000)
        self.assertEqual(o.total, 600_000 - 50_000 + 30_000)
        self.assertEqual(Coupon.objects.get().used_count, 1)

    def test_quote_endpoint(self):
        self.add(self.p1)
        r = self.client.get(reverse("orders:quote"), {"province": "Cần Thơ", "method": self.std.pk})
        d = r.json()
        self.assertEqual(d["shipping_fee"], 40_000)
        self.assertFalse(d["fees"][str(self.exp.pk)]["available"])


class OrderAccessTests(BaseShopTest):
    def _place(self):
        self.add(self.p1)
        self.checkout()
        return Order.objects.get()

    def test_owner_session_can_view(self):
        o = self._place()
        self.assertEqual(self.client.get(reverse("orders:detail", args=[o.code])).status_code, 200)

    def test_stranger_cannot_view_without_token(self):
        o = self._place()
        other = self.client_class()
        self.assertEqual(other.get(reverse("orders:detail", args=[o.code])).status_code, 404)
        self.assertEqual(other.get(o.get_absolute_url()).status_code, 200)

    def test_lookup_by_phone(self):
        o = self._place()
        other = self.client_class()
        r = other.post(reverse("orders:lookup"), {"code": o.code, "contact": "0901234567"})
        self.assertEqual(r.status_code, 302)

    def test_customer_can_cancel_and_stock_returns(self):
        o = self._place()
        self.client.post(reverse("orders:cancel", args=[o.code]), {"reason": "Đặt nhầm"})
        o.refresh_from_db()
        self.p1.refresh_from_db()
        self.assertEqual(o.status, Order.Status.CANCELLED)
        self.assertEqual(self.p1.stock, 10)


class StatusWorkflowTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.add(self.p1)
        self.checkout()
        self.order = Order.objects.get()

    def test_invalid_transition(self):
        with self.assertRaises(ValueError):
            services.change_status(self.order, Order.Status.DELIVERED)

    def test_cod_marked_paid_on_delivery(self):
        Order.objects.filter(pk=self.order.pk).update(carrier="GHN", tracking_number="GHN123456789")
        for s in ["confirmed", "packing", "shipping", "delivered"]:
            self.order = services.change_status(self.order, s)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(self.order.history.count(), 5)


# ---------------------------------------------------------------- payments
@override_settings(PAYMENT_MODE="mock", SITE_URL="http://testserver")
class PaymentTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.add(self.p1)
        self.checkout(payment_method="vnpay")
        self.order = Order.objects.get()

    def _gateway_params(self):
        r = self.client.post(reverse("payments:start", args=[self.order.code]))
        self.assertEqual(r.status_code, 302)
        url = urllib.parse.urlparse(r.url)
        return url.path, dict(urllib.parse.parse_qsl(url.query))

    def test_redirect_is_signed(self):
        path, params = self._gateway_params()
        self.assertEqual(path, reverse("payments:mock_gateway"))
        self.assertTrue(gateway.verify_signature(params, gateway.secret_for("mock")))
        self.assertEqual(int(params["vnp_Amount"]), self.order.total * 100)

    def test_successful_payment_marks_order_paid(self):
        path, params = self._gateway_params()
        r = self.client.post(path + "?" + urllib.parse.urlencode(params), {"outcome": "success"})
        self.assertEqual(r.status_code, 302)
        self.client.get(r.url)  # return URL (idempotent second processing)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        self.assertEqual(Payment.objects.get().status, Payment.Status.SUCCESS)

    def test_failed_payment(self):
        path, params = self._gateway_params()
        self.client.post(path + "?" + urllib.parse.urlencode(params), {"outcome": "fail"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.FAILED)

    def test_tampered_callback_rejected(self):
        _, params = self._gateway_params()
        forged = gateway.mock_result_params(params, "success")
        forged["vnp_Amount"] = "100"  # attacker lowers amount after signing
        r = self.client.get(reverse("payments:ipn"), forged)
        self.assertEqual(r.json()["RspCode"], "97")
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.payment_status, Order.PaymentStatus.PAID)

    def test_ipn_idempotent(self):
        _, params = self._gateway_params()
        result = gateway.mock_result_params(params, "success")
        self.assertEqual(self.client.get(reverse("payments:ipn"), result).json()["RspCode"], "00")
        self.assertEqual(self.client.get(reverse("payments:ipn"), result).json()["RspCode"], "02")

    def test_unsigned_gateway_request_rejected(self):
        path, params = self._gateway_params()
        params["vnp_Amount"] = "1000"
        self.assertEqual(self.client.get(path, params).status_code, 400)


# ---------------------------------------------------------------- security
class SecurityTests(BaseShopTest):
    def test_dashboard_requires_staff(self):
        User.objects.create_user("cust", "c@x.com", "Passw0rd!x")
        self.client.login(username="cust", password="Passw0rd!x")
        r = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(r.status_code, 404)  # a customer is not told that the page exists

    def test_staff_dashboard_renders(self):
        User.objects.create_superuser("boss", "b@x.com", "Passw0rd!x")
        self.client.login(username="boss", password="Passw0rd!x")
        for name in ("dashboard:overview", "dashboard:orders", "dashboard:products", "dashboard:customers"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_login_lockout_after_failures(self):
        User.objects.create_user("victim", "v@x.com", "Passw0rd!x")
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "victim", "password": "wrong"})
        self.client.post(reverse("accounts:login"), {"username": "victim", "password": "Passw0rd!x"})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_with_email(self):
        User.objects.create_user("mail", "mail@x.com", "Passw0rd!x")
        self.client.post(reverse("accounts:login"), {"username": "mail@x.com", "password": "Passw0rd!x"})
        self.assertIn("_auth_user_id", self.client.session)

    def test_security_headers(self):
        r = self.client.get(reverse("pages:home"))
        self.assertIn("Content-Security-Policy", r)
        self.assertEqual(r["X-Frame-Options"], "DENY")

    def test_registration_records_consent(self):
        self.client.post(reverse("accounts:register"), {
            "username": "newbie", "first_name": "A", "last_name": "B", "email": "n@x.com", "phone": "0912345678",
            "password1": "Str0ng!Pass", "password2": "Str0ng!Pass", "data_consent": "on",
        })
        u = User.objects.get(username="newbie")
        self.assertIsNotNone(u.data_consent_at)

    def test_registration_requires_consent(self):
        self.client.post(reverse("accounts:register"), {
            "username": "nope", "first_name": "A", "last_name": "B", "email": "nope@x.com",
            "password1": "Str0ng!Pass", "password2": "Str0ng!Pass",
        })
        self.assertFalse(User.objects.filter(username="nope").exists())

    def test_data_export_and_delete(self):
        User.objects.create_user("me", "me@x.com", "Passw0rd!x")
        self.client.login(username="me", password="Passw0rd!x")
        data = json.loads(self.client.get(reverse("accounts:export_data")).content)
        self.assertEqual(data["account"]["email"], "me@x.com")
        self.client.post(reverse("accounts:delete_account"), {"confirm": "XOA"})
        u = User.objects.get(pk=User.objects.get(email__startswith="deleted-").pk)
        self.assertFalse(u.is_active)


# ---------------------------------------------------------------- search, recommendations, chatbot
class SearchTests(BaseShopTest):
    def test_accent_insensitive_search(self):
        r = self.client.get(reverse("catalog:list"), {"q": "ban di"})
        self.assertContains(r, "G640")

    def test_autocomplete(self):
        r = self.client.get(reverse("catalog:autocomplete"), {"q": "superlight"})
        self.assertEqual(len(r.json()["results"]), 1)


class RecommendationTests(BaseShopTest):
    def test_copurchase_signal(self):
        for _ in range(3):
            self.client = self.client_class()
            self.add(self.m1)
            self.add(self.p1)
            self.checkout()
        engine.invalidate()
        self.assertIn(self.p1, engine.frequently_bought_together(self.m1))

    def test_content_similarity_same_category(self):
        engine.invalidate()
        self.assertEqual(engine.similar_products(self.m1)[0], self.m2)

    def test_trending_fallback(self):
        r = self.client.get(reverse("pages:home"))
        self.assertEqual(r.status_code, 200)


class ChatbotTests(BaseShopTest):
    def test_budget_parsing(self):
        self.assertEqual(parse_budget("duoi 1 trieu"), (None, 1_000_000))
        self.assertEqual(parse_budget("tam 1tr5")[1], int(1_500_000 * 1.2))
        self.assertEqual(parse_budget("500k"), (375_000, 600_000))

    def test_intents(self):
        self.assertEqual(detect_intent(extract("phí ship bao nhiêu")), "shipping")
        self.assertEqual(detect_intent(extract("chính sách đổi trả")), "returns")
        self.assertEqual(detect_intent(extract("chuột fps dưới 1 triệu")), "recommend")

    def test_recommend_respects_budget(self):
        r = self.client.post(reverse("chatbot:message"), json.dumps({"message": "chuột dưới 1 triệu"}), content_type="application/json")
        d = r.json()
        self.assertEqual(d["intent"], "recommend")
        self.assertEqual([p["name"] for p in d["products"]], ["Logitech G304"])

    def test_order_status_privacy(self):
        self.add(self.p1)
        self.checkout()
        o = Order.objects.get()
        other = self.client_class()
        d = other.post(reverse("chatbot:message"), json.dumps({"message": f"đơn {o.code}"}), content_type="application/json").json()
        self.assertNotIn(o.full_name, d["reply"])
        self.assertNotIn("Chờ xác nhận", d["reply"])
        d = self.client.post(reverse("chatbot:message"), json.dumps({"message": f"đơn {o.code}"}), content_type="application/json").json()
        self.assertIn("Chờ xác nhận", d["reply"])


class PageSmokeTests(BaseShopTest):
    def test_public_pages_render(self):
        urls = [reverse("pages:home"), reverse("catalog:list"), self.m1.get_absolute_url(), reverse("cart:detail"), reverse("pages:faq"),
                reverse("pages:contact"), reverse("pages:about"), reverse("orders:lookup"), "/sitemap.xml", "/robots.txt",
                reverse("catalog:category", args=["chuot"]), reverse("catalog:compare") + f"?ids={self.m1.pk},{self.m2.pk}"]
        urls += [reverse("pages:policy", args=[s]) for s in ("dieu-khoan", "bao-mat", "doi-tra", "van-chuyen", "bao-hanh", "thanh-toan", "giai-quyet-khieu-nai")]
        for u in urls:
            self.assertEqual(self.client.get(u).status_code, 200, u)

    def test_404(self):
        self.assertEqual(self.client.get("/khong-ton-tai/").status_code, 404)
