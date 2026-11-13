"""KPI calculations for the management dashboard (Part 2.4 KPIs + Part 5 analytics).

Definitions (also documented in the report):
* Revenue            = Σ total of orders not cancelled/returned, by order date
* Gross profit       = Σ (unit_price − unit_cost) × qty over the same orders
* Orders / AOV       = count of those orders; revenue ÷ orders
* Visits             = unique (session, day) pairs recorded by VisitTrackingMiddleware
* Conversion rate    = orders ÷ visits in the period
* Active users (MAU) = distinct sessions that visited in a calendar month
* New customers      = accounts registered in the period
* Retention rate     = customers who ordered in the previous period AND again
                       in this period ÷ customers who ordered in the previous period
* Repeat-purchase %  = customers with ≥ 2 orders ÷ customers with ≥ 1 order (all time)
"""
from bisect import bisect_left
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import Count, F, Max, Sum, Value
from django.db.models.functions import Coalesce, NullIf, TruncDate, TruncMonth
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.chatbot.models import ChatMessage
from apps.orders.models import Order, OrderItem
from apps.recommendations.models import SearchLog, SiteVisit

LOST = [Order.Status.CANCELLED, Order.Status.RETURNED]
SEGMENTS = ["VIP", "Trung thành", "Mới", "Có nguy cơ rời bỏ"]


def valid_orders():
    return Order.objects.exclude(status__in=LOST)


def _period(days):
    end = timezone.now()
    start = end - timedelta(days=days)
    prev_start = start - timedelta(days=days)
    return prev_start, start, end


def _growth(cur, prev):
    if not prev:
        return None
    return round(100 * (cur - prev) / prev, 1)


def kpis(days=30):
    prev_start, start, end = _period(days)
    cur = valid_orders().filter(created_at__gte=start, created_at__lte=end)
    prev = valid_orders().filter(created_at__gte=prev_start, created_at__lt=start)

    revenue = cur.aggregate(s=Sum("total"))["s"] or 0
    prev_revenue = prev.aggregate(s=Sum("total"))["s"] or 0
    n_orders, prev_orders = cur.count(), prev.count()
    profit = (
        OrderItem.objects.filter(order__in=cur).aggregate(p=Sum((F("unit_price") - F("unit_cost")) * F("quantity")))["p"] or 0
    )
    visits = SiteVisit.objects.filter(day__gte=start.date(), day__lte=end.date()).count()
    prev_visits = SiteVisit.objects.filter(day__gte=prev_start.date(), day__lt=start.date()).count()
    conv = round(100 * n_orders / visits, 2) if visits else 0
    prev_conv = round(100 * prev_orders / prev_visits, 2) if prev_visits else 0

    prev_customers = set(prev.exclude(user=None).values_list("user_id", flat=True))
    cur_customers = set(cur.exclude(user=None).values_list("user_id", flat=True))
    retention = round(100 * len(prev_customers & cur_customers) / len(prev_customers), 1) if prev_customers else 0

    per_user = valid_orders().exclude(user=None).values("user").annotate(n=Count("id"))
    buyers = per_user.count()
    repeaters = per_user.filter(n__gte=2).count()

    new_users = User.objects.filter(date_joined__gte=start, is_staff=False).count()
    prev_new_users = User.objects.filter(date_joined__gte=prev_start, date_joined__lt=start, is_staff=False).count()
    cancelled = Order.objects.filter(created_at__gte=start, status=Order.Status.CANCELLED).count()
    all_cur = Order.objects.filter(created_at__gte=start).count()

    return {
        "days": days,
        "revenue": revenue,
        "revenue_growth": _growth(revenue, prev_revenue),
        "orders": n_orders,
        "orders_growth": _growth(n_orders, prev_orders),
        "aov": int((2 * revenue + n_orders) // (2 * n_orders)) if n_orders else 0,  # rounded half up, like the invoice
        "profit": profit,
        "margin": round(100 * profit / revenue, 1) if revenue else 0,
        "visits": visits,
        "conversion": conv,
        "conversion_delta": round(conv - prev_conv, 2),
        "new_users": new_users,
        "new_users_growth": _growth(new_users, prev_new_users),
        "retention": retention,
        "repeat_rate": round(100 * repeaters / buyers, 1) if buyers else 0,
        "cancel_rate": round(100 * cancelled / all_cur, 1) if all_cur else 0,
        "pending": Order.objects.filter(status=Order.Status.PENDING).count(),
        "awaiting_payment": Order.objects.filter(payment_method=Order.PaymentMethod.BANK, payment_status=Order.PaymentStatus.UNPAID).exclude(status__in=LOST).count(),
    }


def revenue_by_day(days=30):
    start = timezone.now() - timedelta(days=days)
    rows = (
        valid_orders().filter(created_at__gte=start).annotate(d=TruncDate("created_at")).values("d").annotate(rev=Sum("total"), n=Count("id")).order_by("d")
    )
    by_day = {r["d"]: r for r in rows}
    labels, revenue, orders = [], [], []
    for i in range(days, -1, -1):
        d = (timezone.localtime() - timedelta(days=i)).date()
        labels.append(d.strftime("%d/%m"))
        revenue.append(by_day.get(d, {}).get("rev", 0) or 0)
        orders.append(by_day.get(d, {}).get("n", 0) or 0)
    return {"labels": labels, "revenue": revenue, "orders": orders}


def monthly_series(months=6):
    # the last `months` calendar months, ending with the current one
    this_month = timezone.localtime().date().replace(day=1)
    y, m = divmod(this_month.year * 12 + this_month.month - 1 - (months - 1), 12)
    first_day = this_month.replace(year=y, month=m + 1)
    start = timezone.make_aware(datetime.combine(first_day, time.min))  # local midnight on the 1st
    rev = {r["m"].strftime("%m/%Y"): r for r in valid_orders().filter(created_at__gte=start).annotate(m=TruncMonth("created_at")).values("m").annotate(rev=Sum("total"), n=Count("id"))}
    users = {r["m"].strftime("%m/%Y"): r["n"] for r in User.objects.filter(date_joined__gte=start, is_staff=False).annotate(m=TruncMonth("date_joined")).values("m").annotate(n=Count("id"))}
    mau = {r["m"].strftime("%m/%Y"): r["n"] for r in SiteVisit.objects.filter(day__gte=first_day).annotate(m=TruncMonth("day")).values("m").annotate(n=Count("session_key", distinct=True))}
    labels, revenue, orders, new_users, active = [], [], [], [], []
    cursor = first_day
    for _ in range(months):
        key = cursor.strftime("%m/%Y")
        labels.append(key)
        revenue.append(rev.get(key, {}).get("rev", 0) or 0)
        orders.append(rev.get(key, {}).get("n", 0) or 0)
        new_users.append(users.get(key, 0))
        active.append(mau.get(key, 0))
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return {"labels": labels, "revenue": revenue, "orders": orders, "new_users": new_users, "active_users": active}


def top_products(days=30, limit=8):
    start = timezone.now() - timedelta(days=days)
    return (
        OrderItem.objects.filter(order__created_at__gte=start)
        .exclude(order__status__in=LOST)
        .values("product_id", "product_name")
        .annotate(qty=Sum("quantity"), revenue=Sum(F("unit_price") * F("quantity")))
        .order_by("-revenue")[:limit]
    )


def category_share(days=30):
    start = timezone.now() - timedelta(days=days)
    return list(
        OrderItem.objects.filter(order__created_at__gte=start)
        .exclude(order__status__in=LOST)
        # the product's current category; the snapshot taken at sale time once the product is gone
        .values(name=Coalesce("product__category__name", NullIf("category_name", Value(""))))
        .annotate(revenue=Sum(F("unit_price") * F("quantity")))
        .order_by("-revenue")
    )


def breakdowns(days=30):
    start = timezone.now() - timedelta(days=days)
    orders = Order.objects.filter(created_at__gte=start)
    return {
        "status": list(orders.values("status").annotate(n=Count("id")).order_by("-n")),
        "payment": list(orders.exclude(status__in=LOST).values("payment_method").annotate(n=Count("id")).order_by("-n")),
        "delivery": list(orders.values(name=F("delivery_method__name")).annotate(n=Count("id")).order_by("-n")),
        "sources": list(SiteVisit.objects.filter(day__gte=start.date()).values("source").annotate(n=Count("id")).order_by("-n")[:6]),
        "provinces": list(orders.exclude(status__in=LOST).values("province").annotate(n=Count("id"), rev=Sum("total")).order_by("-rev")[:6]),
    }


def search_insights(days=30, limit=8):
    start = timezone.now() - timedelta(days=days)
    logs = SearchLog.objects.filter(created_at__gte=start)
    return {
        "top": list(logs.values("query").annotate(n=Count("id")).order_by("-n")[:limit]),
        "zero": list(logs.filter(results=0).values("query").annotate(n=Count("id")).order_by("-n")[:limit]),
    }


def chatbot_insights(days=30):
    start = timezone.now() - timedelta(days=days)
    msgs = ChatMessage.objects.filter(created_at__gte=start, role="user")
    total = msgs.count()
    unknown = msgs.filter(intent="unknown").count()
    return {
        "total": total,
        "sessions": msgs.values("session_key").distinct().count(),
        "resolved_rate": round(100 * (total - unknown) / total, 1) if total else 0,
        "intents": list(msgs.values("intent").annotate(n=Count("id")).order_by("-n")[:8]),
        "unanswered": list(msgs.filter(intent="unknown").order_by("-created_at").values_list("text", flat=True)[:6]),
    }


def low_stock(limit=10):
    return Product.objects.active().filter(stock__lte=settings.LOW_STOCK_THRESHOLD).order_by("stock")[:limit]


def _quintile_scorer(values):
    """1–5 score of a value against all customers (5 = top 20%). Ties get the same score."""
    ordered = sorted(values)
    n = len(ordered)

    def score(v):
        below = bisect_left(ordered, v)  # customers strictly below this value
        return min(5, 1 + 5 * below // n) if n else 1

    return score


def customer_segments():
    """RFM segmentation of registered customers.

    Recency, Frequency and Monetary are each scored 1–5 by quintile against the whole customer base,
    so segments stay meaningful whatever the shop's price level (fixed thresholds put most of a
    gaming-gear customer base in "VIP"):
    * VIP                = R ≥ 4, F ≥ 4 and M ≥ 4 — the top fifth on all three axes
    * Có nguy cơ rời bỏ  = no order for more than 90 days, or used to buy often (F ≥ 3) but R ≤ 2
    * Trung thành        = at least 2 orders and R ≥ 3
    * Mới                = everyone else (mostly one recent order)
    """
    now = timezone.now()
    rows = list(
        valid_orders()
        .exclude(user=None)
        .values("user_id", "user__username", "user__first_name", "user__last_name", "user__email", "user__phone")
        .annotate(n=Count("id"), spent=Sum("total"), last=Max("created_at"))
        .order_by("-spent")
    )
    for r in rows:
        r["recency"] = (now - r["last"]).days
    r_score = _quintile_scorer([-r["recency"] for r in rows])  # more recent = higher
    f_score = _quintile_scorer([r["n"] for r in rows])
    m_score = _quintile_scorer([r["spent"] for r in rows])
    out = []
    for r in rows:
        R, F, M = r_score(-r["recency"]), f_score(r["n"]), m_score(r["spent"])
        if R >= 4 and F >= 4 and M >= 4:
            seg = "VIP"
        elif r["recency"] > 90 or (F >= 3 and R <= 2):
            seg = "Có nguy cơ rời bỏ"
        elif r["n"] >= 2 and R >= 3:
            seg = "Trung thành"
        else:
            seg = "Mới"
        out.append({**r, "r": R, "f": F, "m": M, "rfm": f"{R}{F}{M}", "segment": seg})
    return out
