"""Simulated card page, bank-transfer test button, and the staff dashboard's charts staying in step with the data."""
import io
import json
import urllib.parse
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.management.commands import seed_demo
from apps.catalog.models import Product
from apps.dashboard import analytics
from apps.dashboard.views import source_label
from apps.orders.models import Order, OrderItem
from apps.payments import gateway
from apps.payments.models import Payment
from apps.recommendations.models import SiteVisit

from .test_shop import BaseShopTest


@override_settings(PAYMENT_MODE="mock", ALLOW_MOCK_PAYMENTS=True, SITE_URL="http://testserver")
class MockCardPageTests(BaseShopTest):
    def test_bank_list_and_full_width_card_field(self):
        self.add(self.m1)
        self.checkout(payment_method="vnpay")
        order = Order.objects.get()
        r = self.client.post(reverse("payments:start", args=[order.code]))
        page = self.client.get(r["Location"]).content.decode()
        self.assertGreaterEqual(page.count("<option value="), 15)
        for bank in ("Vietcombank", "BIDV", "VietinBank", "Agribank", "MB Bank", "ACB", "TPBank", "Sacombank"):
            self.assertIn(bank, page)
        # a typed <input> picks up the same full-width style as the bank <select>
        self.assertIn('<input type="text" id="cardno"', page)
        self.assertIn(gateway.MOCK_TEST_CARD, page)


class BankTransferSimulationTests(BaseShopTest):
    def order(self):
        self.add(self.p1)
        self.checkout(payment_method="bank")
        return Order.objects.get()

    @override_settings(ALLOW_MOCK_PAYMENTS=True)
    def test_simulated_bank_notice_marks_the_order_paid(self):
        o = self.order()
        url = reverse("payments:bank_transfer", args=[o.code])
        self.assertContains(self.client.get(url), "Mô phỏng: ngân hàng báo đã nhận tiền")
        r = self.client.post(reverse("payments:bank_transfer_simulate", args=[o.code]), follow=True)
        o.refresh_from_db()
        self.assertEqual(o.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(o.status, Order.Status.CONFIRMED)
        self.assertContains(r, "Đã nhận thanh toán")
        self.assertNotContains(r, "Mô phỏng: ngân hàng báo đã nhận tiền</button>")  # nothing left to simulate

    @override_settings(ALLOW_MOCK_PAYMENTS=False)
    def test_no_simulation_on_a_real_shop(self):
        o = self.order()
        self.assertNotContains(self.client.get(reverse("payments:bank_transfer", args=[o.code])), "bank_transfer_simulate")
        r = self.client.post(reverse("payments:bank_transfer_simulate", args=[o.code]))
        self.assertEqual(r.status_code, 404)
        o.refresh_from_db()
        self.assertEqual(o.payment_status, Order.PaymentStatus.UNPAID)

    @override_settings(ALLOW_MOCK_PAYMENTS=True)
    def test_someone_else_cannot_mark_an_order_paid(self):
        o = self.order()
        self.client.logout()
        self.client.cookies.clear()
        r = self.client.post(reverse("payments:bank_transfer_simulate", args=[o.code]))
        self.assertEqual(r.status_code, 404)
        o.refresh_from_db()
        self.assertEqual(o.payment_status, Order.PaymentStatus.UNPAID)


class DashboardDataTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user("boss", "boss@example.com", "x-Strong-Pass-9", is_staff=True)

    def buy(self, *products):
        for p in products:
            self.add(p)
        self.checkout()
        return Order.objects.latest("id")

    def test_order_lines_remember_their_category(self):
        self.buy(self.m1, self.p1)
        self.assertEqual(dict(OrderItem.objects.values_list("sku", "category_name")), {"M1": "Chuột gaming", "P1": "Lót chuột"})

    def test_revenue_by_category_survives_deleting_the_product(self):
        self.buy(self.m1, self.p1)
        self.m1.delete()
        share = {c["name"]: c["revenue"] for c in analytics.category_share(30)}
        self.assertEqual(share, {"Chuột gaming": 750_000, "Lót chuột": 600_000})

    def test_sync_backfills_lines_whose_product_was_already_deleted(self):
        self.buy(self.m1)
        OrderItem.objects.update(category_name="")
        self.m1.delete()
        with mock.patch.object(seed_demo, "P", []), mock.patch.object(seed_demo, "RETIRED_BY_CATEGORY", {"chuot": [self.m1.name]}), \
                mock.patch.object(seed_demo, "BRANDS", {}), mock.patch.object(seed_demo, "BANNERS", []):
            call_command("seed_demo", "--sync", stdout=io.StringIO())
        self.assertEqual(OrderItem.objects.get().category_name, "Chuột gaming")

    def test_retired_catalogue_is_grouped_by_existing_categories(self):
        slugs = {row[0] for row in seed_demo.CATEGORIES}
        self.assertLessEqual(set(seed_demo.RETIRED_BY_CATEGORY), slugs)
        self.assertEqual(len(seed_demo.RETIRED), len(set(seed_demo.RETIRED)))

    def test_monthly_chart_ends_with_the_current_month(self):
        labels = analytics.monthly_series(6)["labels"]
        self.assertEqual(len(labels), 6)
        self.assertEqual(labels[-1], timezone.localtime().strftime("%m/%Y"))

    def test_monthly_and_daily_series_agree_with_the_kpis(self):
        self.buy(self.m1)
        self.buy(self.p1)
        k = analytics.kpis(30)
        daily = analytics.revenue_by_day(30)
        self.assertEqual(sum(daily["revenue"]), k["revenue"])
        self.assertEqual(sum(daily["orders"]), k["orders"])
        self.assertEqual(analytics.monthly_series(6)["revenue"][-1], k["revenue"])

    def test_traffic_sources_are_capitalised(self):
        self.assertEqual([source_label(s) for s in ("direct", "google", "tiktok", "youtube", "", "bing")],
                         ["Trực tiếp", "Google", "TikTok", "YouTube", "Trực tiếp", "Bing"])

    def test_overview_page_labels_axes_and_lists_every_category(self):
        self.buy(self.m1, self.p1)
        for i, src in enumerate(("google", "facebook", "direct")):
            SiteVisit.objects.create(session_key=f"s{i}", day=timezone.localdate(), source=src)
        self.client.force_login(self.staff)
        r = self.client.get(reverse("dashboard:overview"))
        page = r.content.decode()
        data = json.loads(page.split('id="chart-data" type="application/json">')[1].split("</script>")[0])
        self.assertEqual(sorted(data["category"]["labels"]), ["Chuột gaming", "Lót chuột"])
        for axis in ("Doanh thu (₫)", "Số đơn (đơn)", "Người dùng (người)", "Ngày (dd/mm)", "Tháng (mm/yyyy)"):
            self.assertIn(axis, page)
        for name in ("Google", "Facebook", "Trực tiếp"):
            self.assertIn(f"<span>{name}</span>", page)
