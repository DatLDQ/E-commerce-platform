"""Regression tests for the issues fixed during the assignment review.

Run:  python manage.py test tests
"""
import io
import json
import urllib.parse
from datetime import timedelta

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forms import ProfileForm
from apps.accounts.models import User
from apps.catalog.models import Product, Review
from apps.chatbot.engine import detect_intent, extract
from apps.orders import services
from apps.orders.models import Coupon, Order
from apps.payments import gateway, vietqr

from .test_shop import BaseShopTest


def chat(client, text):
    return client.post(reverse("chatbot:message"), json.dumps({"message": text}), content_type="application/json").json()


# ---------------------------------------------------------------- orders & payments
class CancelledOrderPaymentTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.add(self.p1)
        self.checkout(payment_method="vnpay")
        self.order = Order.objects.get()

    def test_payment_after_cancel_is_flagged_for_refund_not_resurrected(self):
        r = self.client.post(reverse("payments:start", args=[self.order.code]))
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.url).query))
        services.change_status(self.order, Order.Status.CANCELLED, note="Khách huỷ")
        stock_after_cancel = Product.objects.get(pk=self.p1.pk).stock
        # The gateway confirms the (already started) payment afterwards
        result = gateway.mock_result_params(params, "success")
        self.assertEqual(self.client.get(reverse("payments:ipn"), result).json()["RspCode"], "00")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.REFUNDED)
        self.assertIn("hoàn tiền", self.order.history.last().note)
        self.assertEqual(Product.objects.get(pk=self.p1.pk).stock, stock_after_cancel)  # no double restock

    def test_return_url_uses_request_host(self):
        r = self.client.post(reverse("payments:start", args=[self.order.code]))
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.url).query))
        self.assertTrue(params["vnp_ReturnUrl"].startswith("http://testserver/"))

    def test_expire_unpaid_orders_releases_stock(self):
        stock = Product.objects.get(pk=self.p1.pk).stock
        Order.objects.filter(pk=self.order.pk).update(created_at=timezone.now() - timedelta(hours=2))
        out = io.StringIO()
        call_command("expire_unpaid_orders", minutes=60, stdout=out)
        self.assertIn(self.order.code, out.getvalue())
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(Product.objects.get(pk=self.p1.pk).stock, stock + 1)

    def test_recent_or_cod_orders_are_not_expired(self):
        self.add(self.p1)
        self.checkout()  # COD
        Order.objects.update(created_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(services.expire_unpaid_orders(60), [])
        Order.objects.filter(payment_method="cod").update(created_at=timezone.now() - timedelta(days=3))
        self.assertEqual(services.expire_unpaid_orders(60), [])


class CheckoutHardeningTests(BaseShopTest):
    def test_non_numeric_delivery_method_is_a_form_error_not_500(self):
        self.add(self.p1)
        r = self.checkout(delivery_method="abc")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Order.objects.exists())

    def test_quote_with_garbage_method(self):
        self.add(self.p1)
        r = self.client.get(reverse("orders:quote"), {"province": "Hà Nội", "method": "1 OR 1=1"})
        self.assertEqual(r.status_code, 200)

    def test_ward_required_district_not(self):
        self.add(self.p1)
        r = self.checkout(ward="", district="")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Order.objects.exists())
        self.checkout(district="")
        self.assertEqual(Order.objects.get().district, "")

    def test_coupon_slot_returned_on_cancel(self):
        c = Coupon.objects.create(code="SALE", kind=Coupon.FIXED, value=50_000, usage_limit=1)
        self.add(self.p1)
        self.client.post(reverse("cart:coupon"), {"code": "SALE"})
        self.checkout()
        c.refresh_from_db()
        self.assertEqual(c.used_count, 1)
        o = Order.objects.get()
        self.client.post(reverse("orders:cancel", args=[o.code]) + f"?t={o.access_token}", {"reason": "Đặt nhầm"})
        c.refresh_from_db()
        self.assertEqual(c.used_count, 0)


class ProvinceReformTests(BaseShopTest):
    def test_34_units(self):
        self.assertEqual(len(services.PROVINCES), 34)
        self.assertEqual(len(set(services.PROVINCES)), 34)
        self.assertTrue(set(services.LEGACY_PROVINCES.values()) <= set(services.PROVINCES))
        self.assertTrue(set(services.LEGACY_PROVINCES).isdisjoint(services.PROVINCES))

    def test_legacy_names_mapped(self):
        self.assertEqual(services.normalize_province("Bình Dương"), "TP. Hồ Chí Minh")
        self.assertEqual(services.normalize_province("Quảng Nam"), "Đà Nẵng")
        self.assertEqual(services.normalize_province("Hà Nội"), "Hà Nội")

    def test_old_province_rejected_at_checkout(self):
        self.add(self.p1)
        self.checkout(province="Bình Dương")
        self.assertFalse(Order.objects.exists())


class VietQRTests(BaseShopTest):
    def test_crc16_ccitt_false_check_value(self):
        self.assertEqual(vietqr.crc16_ccitt("123456789"), "29B1")

    def test_payload_structure(self):
        payload = vietqr.build_payload("970436", "0001 2345 67890", 1_350_000, "LEVELUP LU2610250A1B2C")
        self.assertTrue(payload.startswith("000201010212"))
        self.assertIn("0010A000000727", payload)
        self.assertIn("0006970436", payload)
        self.assertIn("01130001234567890", payload)
        self.assertIn("54071350000", payload)
        self.assertIn("5802VN", payload)
        self.assertEqual(payload[-8:-4], "6304")
        self.assertEqual(payload[-4:], vietqr.crc16_ccitt(payload[:-4]))

    def test_bank_transfer_page(self):
        self.add(self.p1)
        self.checkout(payment_method="bank")
        o = Order.objects.get()
        r = self.client.get(reverse("payments:bank_transfer", args=[o.code]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["qr_payload"].startswith("000201"))


# ---------------------------------------------------------------- chatbot
class ChatbotMatchingTests(BaseShopTest):
    def test_whole_word_intents(self):
        # "hong" (broken) must not fire inside "khong"
        self.assertEqual(detect_intent(extract("tai nghe không dây có tốt không")), "recommend")
        # "cod" must not fire inside "code"
        self.assertEqual(detect_intent(extract("có code giảm giá không")), "promotion")
        # "hi" must not fire inside "phi"
        self.assertEqual(detect_intent(extract("phí ship ra Hà Nội?")), "shipping")
        self.assertEqual(detect_intent(extract("Hi shop")), "greeting")
        self.assertEqual(detect_intent(extract("chuột bị hỏng thì sao")), "returns")

    def test_longest_category_wins(self):
        self.assertEqual(extract("lót chuột cỡ lớn")["category"], "lot-chuot")
        self.assertEqual(extract("chuột không dây")["category"], "chuot")

    def test_brand_detection(self):
        self.assertEqual(extract("chuột Logitech G nào ngon")["brand"].name, "Logitech G")

    def test_follow_up_cheaper(self):
        d = chat(self.client, "chuột fps")
        self.assertEqual(d["intent"], "recommend")
        self.assertIn("Logitech G Pro Superlight", [p["name"] for p in d["products"]])
        d = chat(self.client, "Rẻ hơn chút")
        self.assertEqual(d["intent"], "recommend")
        self.assertEqual([p["name"] for p in d["products"]], [])  # cheapest shown was G304 — nothing cheaper
        d = chat(self.client, "chuột trên 2 triệu")
        self.assertEqual([p["name"] for p in d["products"]], ["Logitech G Pro Superlight"])
        d = chat(self.client, "Rẻ hơn chút")
        self.assertEqual([p["name"] for p in d["products"]], ["Logitech G304"])

    def test_follow_up_keeps_category(self):
        chat(self.client, "lót chuột")
        d = chat(self.client, "Loại không dây thì sao?")
        self.assertEqual(d["intent"], "recommend")
        # mousepads stay mousepads (tag relaxed when nothing matches)
        self.assertEqual([p["name"] for p in d["products"]], ["Logitech G640 Bàn di"])

    def test_no_context_follow_up_is_unknown(self):
        self.assertEqual(chat(self.client, "Rẻ hơn chút")["intent"], "unknown")


# ---------------------------------------------------------------- catalogue, accounts, dashboard
class CatalogueFixTests(BaseShopTest):
    def test_slug_keeps_d_stroke(self):
        p = Product.objects.create(category=self.m1.category, brand=self.m1.brand, name="Chuột Đen Đỏ", sku="X9", price=100_000)
        self.assertEqual(p.slug, "chuot-den-do")

    def test_rating_sort_puts_unrated_last(self):
        u = User.objects.create_user("r", "r@x.com", "Passw0rd!x")
        Review.objects.create(product=self.p1, user=u, rating=4, comment="ok")
        r = self.client.get(reverse("catalog:list"), {"sort": "rating"})
        names = [p.name for p in r.context["page"].object_list]
        self.assertEqual(names[0], self.p1.name)


class AccountAndDashboardFixTests(BaseShopTest):
    def test_profile_email_unique_case_insensitive(self):
        User.objects.create_user("a", "taken@x.com", "Passw0rd!x")
        me = User.objects.create_user("b", "me@x.com", "Passw0rd!x")
        form = ProfileForm({"email": "TAKEN@x.com"}, instance=me)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        form = ProfileForm({"email": "ME@x.com"}, instance=me)
        self.assertTrue(form.is_valid(), form.errors)

    def test_dashboard_ignores_foreign_referer(self):
        User.objects.create_superuser("boss", "b@x.com", "Passw0rd!x")
        self.client.login(username="boss", password="Passw0rd!x")
        r = self.client.post(reverse("dashboard:product_toggle", args=[self.m1.pk]), HTTP_REFERER="https://evil.example/phish")
        self.assertEqual(r.url, reverse("dashboard:products"))
        r = self.client.post(reverse("dashboard:product_stock", args=[self.m1.pk]), {"delta": 1}, HTTP_REFERER="http://testserver/dashboard/san-pham/?q=g")
        self.assertEqual(r.url, "http://testserver/dashboard/san-pham/?q=g")

    def test_error_page_renders_without_middleware_attributes(self):
        # e.g. a 404 raised before SessionMiddleware/AuthenticationMiddleware ran
        from django.test import RequestFactory

        from apps.pages.errors import not_found

        r = not_found(RequestFactory().get("/static/missing.css"))
        self.assertEqual(r.status_code, 404)
