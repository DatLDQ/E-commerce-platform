"""Regression tests for the production-hardening fixes (audit 11/2026):

C1  demo superuser password never used outside DEBUG
C2  simulated gateway (MoMo / VNPay without keys) disabled unless ALLOW_MOCK_PAYMENTS
C3  site refuses to boot in production with placeholder secrets
H1  dashboard multi-image upload works and only accepts real images

Run:  python manage.py test tests
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User
from apps.catalog.management.commands.seed_demo import DEMO_ADMIN_PASSWORD, Command as SeedCommand
from apps.catalog.models import ProductImage
from apps.orders.forms import CheckoutForm
from apps.orders.models import Order
from apps.payments import gateway
from apps.payments.models import Payment
from config.secrets_check import insecure_settings

from .test_shop import BaseShopTest

BASE_DIR = Path(__file__).resolve().parent.parent
STRONG = "x7Qp2vLr9sKt4wZy8bNc3mHd6fJg1aEu5"  # 33 chars, no placeholder marker


# ---------------------------------------------------------------- C1 demo admin
class SeedAdminPasswordTests(BaseShopTest):
    def _seed(self):
        cmd = SeedCommand(stdout=io.StringIO())
        return cmd

    @override_settings(DEBUG=True)
    def test_debug_uses_demo_password(self):
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": ""}):
            self.assertEqual(self._seed()._admin_password(), DEMO_ADMIN_PASSWORD)

    @override_settings(DEBUG=False)
    def test_production_without_env_has_no_password(self):
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": ""}):
            self.assertIsNone(self._seed()._admin_password())

    @override_settings(DEBUG=False)
    def test_production_uses_env_password(self):
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": STRONG}):
            self.assertEqual(self._seed()._admin_password(), STRONG)

    @override_settings(DEBUG=False)
    def test_existing_admin_with_demo_password_is_locked(self):
        User.objects.create_superuser("admin", "a@x.com", DEMO_ADMIN_PASSWORD)
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": ""}):
            self._seed()._secure_admin()
        admin = User.objects.get(username="admin")
        self.assertFalse(admin.has_usable_password())
        self.assertFalse(self.client.login(username="admin", password=DEMO_ADMIN_PASSWORD))

    @override_settings(DEBUG=False)
    def test_existing_admin_with_demo_password_gets_env_password(self):
        User.objects.create_superuser("admin", "a@x.com", DEMO_ADMIN_PASSWORD)
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": STRONG}):
            self._seed()._secure_admin()
        self.assertTrue(User.objects.get(username="admin").check_password(STRONG))

    @override_settings(DEBUG=False)
    def test_admin_own_password_is_left_alone(self):
        User.objects.create_superuser("admin", "a@x.com", "Their-own-Passw0rd!")
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": STRONG}):
            self._seed()._secure_admin()
        self.assertTrue(User.objects.get(username="admin").check_password("Their-own-Passw0rd!"))


# ---------------------------------------------------------------- C2 simulated gateway
@override_settings(PAYMENT_MODE="mock", ALLOW_MOCK_PAYMENTS=True, SITE_URL="http://testserver")
class MockGatewayDisabledTests(BaseShopTest):
    """Orders started while the simulator was on; then it is switched off (or never on)."""

    def setUp(self):
        super().setUp()
        self.add(self.p1)
        self.checkout(payment_method="momo")
        self.order = Order.objects.get()
        r = self.client.post(reverse("payments:start", args=[self.order.code]))
        self.params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.url).query))

    @override_settings(ALLOW_MOCK_PAYMENTS=False)
    def test_simulator_page_is_404(self):
        url = reverse("payments:mock_gateway") + "?" + urllib.parse.urlencode(self.params)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"outcome": "success"}).status_code, 404)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)

    @override_settings(ALLOW_MOCK_PAYMENTS=False)
    def test_correctly_signed_mock_ipn_is_rejected(self):
        result = gateway.mock_result_params(self.params, "success")  # valid HMAC with the mock secret
        self.assertEqual(self.client.get(reverse("payments:ipn"), result).json()["RspCode"], "97")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.UNPAID)
        self.assertEqual(Payment.objects.get().status, Payment.Status.PENDING)

    @override_settings(ALLOW_MOCK_PAYMENTS=False)
    def test_starting_payment_without_gateway_shows_error(self):
        r = self.client.post(reverse("payments:start", args=[self.order.code]), follow=True)
        self.assertContains(r, "Hiện chưa thể thanh toán qua Ví MoMo")
        self.assertEqual(Payment.objects.count(), 1)  # no new attempt created

    def test_simulator_still_works_when_allowed(self):
        url = reverse("payments:mock_gateway") + "?" + urllib.parse.urlencode(self.params)
        self.client.post(url, {"outcome": "success"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)


class PaymentMethodAvailabilityTests(BaseShopTest):
    def _choices(self):
        return [c for c, _ in CheckoutForm().fields["payment_method"].choices]

    @override_settings(ALLOW_MOCK_PAYMENTS=False, PAYMENT_MODE="mock")
    def test_no_simulator_no_keys_offers_only_cod_and_bank(self):
        self.assertEqual(self._choices(), ["cod", "bank"])

    @override_settings(ALLOW_MOCK_PAYMENTS=False, PAYMENT_MODE="vnpay", VNPAY={"TMN_CODE": "T", "HASH_SECRET": "S", "PAYMENT_URL": "https://x"})
    def test_real_vnpay_keys_offer_vnpay_but_not_momo(self):
        self.assertEqual(self._choices(), ["cod", "vnpay", "bank"])
        self.assertEqual(gateway.gateway_for("vnpay"), "vnpay")
        self.assertIsNone(gateway.gateway_for("momo"))

    @override_settings(ALLOW_MOCK_PAYMENTS=True, PAYMENT_MODE="mock")
    def test_simulator_offers_everything(self):
        self.assertEqual(self._choices(), ["cod", "vnpay", "momo", "bank"])

    @override_settings(ALLOW_MOCK_PAYMENTS=False, PAYMENT_MODE="mock")
    def test_posting_hidden_method_is_rejected(self):
        self.add(self.p1)
        r = self.checkout(payment_method="momo")
        self.assertEqual(r.status_code, 200)  # form re-rendered with an error
        self.assertFalse(Order.objects.exists())


# ---------------------------------------------------------------- C3 production secrets
class ProductionSecretsTests(BaseShopTest):
    def test_debug_never_complains(self):
        self.assertEqual(insecure_settings(debug=True, secret_key="", allow_mock_payments=True, mock_gateway_secret=""), [])

    def test_placeholder_or_short_secret_key(self):
        for key in ("", "dev-only-insecure-key-change-me", "change-me-to-a-long-random-string", "short"):
            self.assertTrue(insecure_settings(debug=False, secret_key=key, allow_mock_payments=False, mock_gateway_secret=""), key)

    def test_mock_secret_only_required_when_simulator_on(self):
        self.assertEqual(insecure_settings(debug=False, secret_key=STRONG, allow_mock_payments=False, mock_gateway_secret="change-me"), [])
        self.assertTrue(insecure_settings(debug=False, secret_key=STRONG, allow_mock_payments=True, mock_gateway_secret="change-me"))
        self.assertEqual(insecure_settings(debug=False, secret_key=STRONG, allow_mock_payments=True, mock_gateway_secret=STRONG), [])

    def _boot(self, **env):
        base = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "MOCK_", "ALLOW_MOCK"))}
        base.update(DJANGO_SETTINGS_MODULE="config.settings", PYTHONIOENCODING="utf-8", **env)
        code = "import django; django.setup(); print('BOOT-OK')"
        return subprocess.run([sys.executable, "-c", code], cwd=BASE_DIR, env=base, capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_production_boot_refused_with_default_secret(self):
        r = self._boot(DJANGO_DEBUG="False", DJANGO_SECRET_KEY="")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", r.stderr)

    def test_production_boot_ok_with_strong_secret(self):
        r = self._boot(DJANGO_DEBUG="False", DJANGO_SECRET_KEY=STRONG, ALLOW_MOCK_PAYMENTS="False")
        self.assertIn("BOOT-OK", r.stdout, r.stderr)


# ---------------------------------------------------------------- H1 image upload
def png_bytes(color=(124, 58, 237)):
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buf, format="PNG")
    return buf.getvalue()


class DashboardImageUploadTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)
        User.objects.create_superuser("boss", "b@x.com", "Passw0rd!x")
        self.client.login(username="boss", password="Passw0rd!x")

    def _post(self, files, product=None):
        p = product or self.m1
        data = {
            "name": p.name, "sku": p.sku, "category": p.category_id, "brand": p.brand_id, "price": p.price,
            "sale_price": p.sale_price or "", "cost_price": 100_000, "stock": p.stock, "warranty_months": 12,
            "weight_grams": p.weight_grams, "is_active": "on", "new_images": files,
        }
        return self.client.post(reverse("dashboard:product_edit", args=[p.pk]), data)

    def test_multiple_real_images_are_saved(self):
        r = self._post([SimpleUploadedFile("a.png", png_bytes(), "image/png"), SimpleUploadedFile("b.png", png_bytes((0, 0, 0)), "image/png")])
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        imgs = list(ProductImage.objects.filter(product=self.m1).order_by("sort_order"))
        self.assertEqual(len(imgs), 2)
        self.assertEqual([i.sort_order for i in imgs], [0, 1])

    def test_no_image_still_saves(self):
        self.assertEqual(self._post([]).status_code, 302)

    def test_fake_png_is_rejected(self):
        r = self._post([SimpleUploadedFile("fake.png", b"not really a png", "image/png")])
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "fake.png")
        self.assertFalse(ProductImage.objects.exists())

    def test_svg_is_rejected(self):
        svg = b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>"
        r = self._post([SimpleUploadedFile("evil.svg", svg, "image/svg+xml")])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ProductImage.objects.exists())

    def test_one_bad_file_rejects_the_batch(self):
        r = self._post([SimpleUploadedFile("ok.png", png_bytes(), "image/png"), SimpleUploadedFile("bad.png", b"x", "image/png")])
        self.assertEqual(r.status_code, 200)
        self.assertFalse(ProductImage.objects.exists())
