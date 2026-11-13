"""Hybrid recommendation engine (Part 5 — AI-based recommendation).

Three signals are combined:

1. **Item-to-item collaborative filtering** — products that appear together in
   the same orders (co-purchase counts, normalised with the cosine/Ochiai
   coefficient so best-sellers don't dominate every list).
2. **Content-based similarity** — cosine similarity over a sparse feature
   vector: category, brand, tags (gamer genre, wireless, rgb…) and a price
   band, so brand-new products with no sales can still be recommended
   (cold-start).
3. **Personalisation** — a user's recent views and purchases are used as
   seeds; candidate scores are accumulated with time decay.

Results fall back to *trending* products (views + sales in the last 30 days)
when there is no signal. Everything is computed in-process and cached, which
is plenty for a catalogue of a few thousand SKUs; for larger catalogues the
same functions can be run as a nightly batch job.
"""
import math
from collections import Counter, defaultdict
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from apps.catalog.models import Product
from apps.orders.models import Order, OrderItem

from .models import ProductView

CACHE_TTL = 600
W_COPURCHASE, W_CONTENT = 0.6, 0.4


# ---------------------------------------------------------------- feature building
def _price_band(price):
    # log-scale price bands: products in the same band are "similar budget"
    return f"price:{int(math.log(max(price, 1), 1.8))}"


def _features(p):
    f = {f"cat:{p.category_id}": 3.0, f"brand:{p.brand_id}": 1.0, _price_band(p.current_price): 1.0}
    for t in p.tag_list:
        f[f"tag:{t}"] = 1.0
    return f


def _cosine(a, b):
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    if not dot:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb)


def _content_matrix():
    data = cache.get("rec:content")
    if data is None:
        products = list(Product.objects.active().only("id", "category_id", "brand_id", "tags", "price", "sale_price"))
        feats = {p.pk: _features(p) for p in products}
        data = {}
        for pid, f in feats.items():
            sims = [(other, _cosine(f, of)) for other, of in feats.items() if other != pid]
            sims = [s for s in sims if s[1] > 0]
            sims.sort(key=lambda x: -x[1])
            data[pid] = dict(sims[:30])
        cache.set("rec:content", data, CACHE_TTL)
    return data


def _copurchase_matrix():
    data = cache.get("rec:copurchase")
    if data is None:
        baskets = defaultdict(set)
        rows = OrderItem.objects.exclude(order__status=Order.Status.CANCELLED).exclude(product__isnull=True).values_list("order_id", "product_id")
        for oid, pid in rows:
            baskets[oid].add(pid)
        item_count, pair_count = Counter(), Counter()
        for items in baskets.values():
            items = sorted(items)
            item_count.update(items)
            for i, a in enumerate(items):
                for b in items[i + 1 :]:
                    pair_count[(a, b)] += 1
        data = defaultdict(dict)
        for (a, b), n in pair_count.items():
            score = n / math.sqrt(item_count[a] * item_count[b])  # Ochiai / cosine
            data[a][b] = score
            data[b][a] = score
        data = dict(data)
        cache.set("rec:copurchase", data, CACHE_TTL)
    return data


def invalidate():
    cache.delete_many(["rec:content", "rec:copurchase", "rec:trending"])


def _fetch(ids, exclude=()):
    ids = [i for i in ids if i not in set(exclude)]
    objs = Product.objects.active().filter(pk__in=ids, stock__gt=0).select_related("brand", "category").prefetch_related("images").with_ratings()
    by_id = {p.pk: p for p in objs}
    return [by_id[i] for i in ids if i in by_id]


# ---------------------------------------------------------------- public API
def similar_products(product, limit=8):
    """Content-based: 'Sản phẩm tương tự'."""
    sims = _content_matrix().get(product.pk, {})
    ranked = sorted(sims, key=lambda k: -sims[k])
    return _fetch(ranked[: limit * 2], exclude=[product.pk])[:limit]


def frequently_bought_together(product, limit=4):
    """Item-item CF: 'Thường được mua cùng'. Falls back to complementary categories."""
    co = _copurchase_matrix().get(product.pk, {})
    ranked = [pid for pid in sorted(co, key=lambda k: -co[k])]
    result = _fetch(ranked[: limit * 2], exclude=[product.pk])
    result = [p for p in result if p.category_id != product.category_id] + [p for p in result if p.category_id == product.category_id]
    return result[:limit]


def hybrid_for_product(product, limit=8):
    """Blend of both — 'Có thể bạn cũng thích'."""
    co = _copurchase_matrix().get(product.pk, {})
    ct = _content_matrix().get(product.pk, {})
    max_co = max(co.values(), default=1) or 1
    scores = Counter()
    for k, v in co.items():
        scores[k] += W_COPURCHASE * v / max_co
    for k, v in ct.items():
        scores[k] += W_CONTENT * v
    ranked = [k for k, _ in scores.most_common(limit * 2)]
    return _fetch(ranked, exclude=[product.pk])[:limit]


def frequently_bought_together_for_cart(cart, limit=4):
    ids = list(cart.items.values_list("product_id", flat=True))
    if not ids:
        return []
    co, ct = _copurchase_matrix(), _content_matrix()
    scores = Counter()
    for pid in ids:
        for k, v in co.get(pid, {}).items():
            scores[k] += v
        for k, v in ct.get(pid, {}).items():
            scores[k] += 0.2 * v
    ranked = [k for k, _ in scores.most_common(limit * 3)]
    return _fetch(ranked, exclude=ids)[:limit]


def trending(limit=8, days=30):
    ids = cache.get("rec:trending")
    if ids is None:
        since = timezone.now() - timedelta(days=days)
        qs = (
            Product.objects.active()
            .annotate(
                recent_views=Count("views", filter=Q(views__created_at__gte=since), distinct=True),
                recent_sales=Count("order_items", filter=Q(order_items__order__created_at__gte=since), distinct=True),
            )
            .order_by("-recent_sales", "-recent_views", "-sold_count")
            .values_list("pk", flat=True)[:40]
        )
        ids = list(qs)
        cache.set("rec:trending", ids, CACHE_TTL)
    return _fetch(ids)[:limit]


def for_user(request, limit=8):
    """Personalised 'Dành riêng cho bạn' list based on views + purchases with time decay."""
    now = timezone.now()
    seeds = Counter()
    views = ProductView.objects.filter(created_at__gte=now - timedelta(days=60))
    if request.user.is_authenticated:
        views = views.filter(user=request.user)
        purchased = OrderItem.objects.filter(order__user=request.user).exclude(order__status=Order.Status.CANCELLED).values_list("product_id", "order__created_at")
        for pid, when in purchased:
            if pid:
                seeds[pid] += 3.0 * 0.5 ** ((now - when).days / 30)
    elif request.session.session_key:
        views = views.filter(session_key=request.session.session_key)
    else:
        return trending(limit)
    for pid, when in views.values_list("product_id", "created_at")[:200]:
        seeds[pid] += 1.0 * 0.5 ** ((now - when).days / 14)  # 2-week half-life
    if not seeds:
        return trending(limit)

    co, ct = _copurchase_matrix(), _content_matrix()
    scores = Counter()
    for seed, w in seeds.items():
        for k, v in co.get(seed, {}).items():
            scores[k] += w * W_COPURCHASE * v
        for k, v in ct.get(seed, {}).items():
            scores[k] += w * W_CONTENT * v
    already_bought = set()
    if request.user.is_authenticated:
        already_bought = set(OrderItem.objects.filter(order__user=request.user).values_list("product_id", flat=True))
    ranked = [k for k, _ in scores.most_common(limit * 3) if k not in already_bought]
    result = _fetch(ranked)[:limit]
    if len(result) < limit:
        result += [p for p in trending(limit * 2) if p not in result and p.pk not in already_bought][: limit - len(result)]
    return result


def recently_viewed(request, limit=6, exclude=None):
    qs = ProductView.objects.all()
    if request.user.is_authenticated:
        qs = qs.filter(user=request.user)
    elif request.session.session_key:
        qs = qs.filter(session_key=request.session.session_key)
    else:
        return []
    seen, ids = set(), []
    for pid in qs.values_list("product_id", flat=True)[:50]:
        if pid not in seen and pid != exclude:
            seen.add(pid)
            ids.append(pid)
    return _fetch(ids[:limit])


def track_view(request, product):
    if not request.session.session_key:
        request.session.save()
    ProductView.objects.create(
        product=product, user=request.user if request.user.is_authenticated else None, session_key=request.session.session_key or ""
    )
