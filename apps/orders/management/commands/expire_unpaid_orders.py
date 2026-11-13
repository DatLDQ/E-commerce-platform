"""python manage.py expire_unpaid_orders [--minutes N]

Cancels online-payment orders that were never paid so their stock goes back
on sale. Schedule it every 15 minutes (cron / Render Cron Job).
"""
from django.core.management.base import BaseCommand

from apps.orders.services import expire_unpaid_orders


class Command(BaseCommand):
    help = "Huỷ các đơn thanh toán online quá hạn chưa thanh toán và hoàn kho"

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, default=None, help="Timeout for VNPay/MoMo orders (default: settings)")

    def handle(self, *args, **opts):
        codes = expire_unpaid_orders(opts["minutes"])
        # ASCII output: safe on any console/log encoding (e.g. cp1258 on Windows)
        self.stdout.write(self.style.SUCCESS(f"Cancelled {len(codes)} unpaid order(s): {', '.join(codes) or '-'}"))
