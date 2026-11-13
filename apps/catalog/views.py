from collections import Counter, defaultdict
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from apps.orders.models import Order, OrderItem
from apps.recommendations import engine
from apps.recommendations.models import SearchLog
from config.utils import login_required_post, safe_next

from .forms import ReviewForm
from .models import Brand, Category, Product, Review, Wishlist
from .utils import strip_accents

SORTS = {
    "new": ("Mới nhất", ["-created_at"]),
    "popular": ("Bán chạy", ["-sold_count", "-view_count"]),
    "price_asc": ("Giá thấp → cao", ["effective_price"]),
    "price_desc": ("Giá cao → thấp", ["-effective_price"]),
    # nulls_last: unrated products must not float to the top on PostgreSQL
    "rating": ("Đánh giá cao", [F("avg_rating").desc(nulls_last=True), "-review_count"]),
}

PRICE_RANGES = [
    ("0-500000", "Dưới 500K"),
    ("500000-1500000", "500K – 1,5 triệu"),
    ("1500000-3000000", "1,5 – 3 triệu"),
    ("3000000-", "Trên 3 triệu"),
]

# ?tag= values linked from the home page tiles, as shown on the "đang lọc" chip
TAG_LABELS = {"fps": "Setup FPS", "moba": "Setup MOBA", "wireless": "Không dây", "rgb": "LED RGB", "streaming": "Góc streamer"}


def filter_products(request, base_qs):
    from django.db.models.functions import Coalesce

    qs = base_qs.with_ratings().annotate(effective_price=Coalesce("sale_price", "price"))
    q = request.GET.get("q", "").strip()
    if q:
        terms = strip_accents(q).split()
        for t in terms:
            qs = qs.filter(search_text__icontains=t)
    brands = request.GET.getlist("brand")
    if brands:
        qs = qs.filter(brand__slug__in=brands)
    price = request.GET.get("price", "")
    if "-" in price:
        lo, _, hi = price.partition("-")
        if lo.isdigit():
            qs = qs.filter(effective_price__gte=int(lo))
        if hi.isdigit():
            qs = qs.filter(effective_price__lte=int(hi))
    if request.GET.get("in_stock"):
        qs = qs.filter(stock__gt=0)
    if request.GET.get("on_sale"):
        qs = qs.filter(sale_price__isnull=False)
    rating = request.GET.get("rating")
    if rating and rating.isdigit():
        qs = qs.filter(avg_rating__gte=int(rating))
    tag = request.GET.get("tag")
    if tag:
        qs = qs.filter(tags__icontains=tag)
    sort = request.GET.get("sort", "popular" if not q else "")
    if sort in SORTS:
        qs = qs.order_by(*SORTS[sort][1], "-id")
    else:  # "relevance" for searches: best-sellers first among matches
        qs = qs.order_by("-sold_count", "-view_count", "-id")
    return qs, q, sort


SEARCH_GROUP_SIZE = 5  # products shown per category on a search page before "Xem thêm"


def categories_by_matches(qs):
    """(counts, categories, order) for the categories `qs` matches: biggest first, ties in the shop's order."""
    counts = Counter(qs.order_by().values_list("category_id", flat=True))
    cats = Category.objects.in_bulk(counts)
    order = sorted(counts, key=lambda c: (-counts[c], cats[c].sort_order, cats[c].name))
    return counts, cats, order


def search_groups(qs, size=SEARCH_GROUP_SIZE):
    """A search across categories, one group per category with its `size` first products (in the page's sort)."""
    counts, cats, order = categories_by_matches(qs)
    return [
        {"category": cats[c], "count": counts[c], "more": max(counts[c] - size, 0), "products": list(qs.filter(category_id=c)[:size])}
        for c in order
    ]


def product_list(request, category_slug=None):
    category = get_object_or_404(Category, slug=category_slug) if category_slug else None
    base = Product.objects.active().select_related("brand", "category").prefetch_related("images")
    if category:
        base = base.filter(category=category)
    qs, q, sort = filter_products(request, base)
    if q and request.GET.get("page", "1") == "1":
        SearchLog.objects.create(query=q[:200], results=qs.count(), user=request.user if request.user.is_authenticated else None)
    page = Paginator(qs, 12).get_page(request.GET.get("page"))
    # a search over the whole shop is shown per category (5 each + "Xem thêm"), so one big category can't hide the rest
    groups = search_groups(qs) if q and not category and page.paginator.count > SEARCH_GROUP_SIZE else []
    if len(groups) < 2:
        groups = []
    # brand / tag have no sidebar control; they arrive from links and are shown as removable chips
    selected_brands = request.GET.getlist("brand")
    tag = request.GET.get("tag", "").strip()
    return render(
        request,
        "catalog/list.html",
        {
            "category": category,
            "page": page,
            "groups": groups,
            "q": q,
            "sort": sort,
            "sorts": [(k, v[0]) for k, v in SORTS.items()],
            "active_brands": list(Brand.objects.filter(slug__in=selected_brands)) if selected_brands else [],
            "active_tag": (tag, TAG_LABELS.get(tag.lower(), tag)) if tag else None,
            "price_ranges": PRICE_RANGES,
            "suggestions": engine.trending(4) if q and not page.paginator.count else [],
        },
    )


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.active().select_related("brand", "category").prefetch_related("images").with_ratings(), slug=slug
    )
    Product.objects.filter(pk=product.pk).update(view_count=F("view_count") + 1)
    engine.track_view(request, product)

    reviews = product.reviews.filter(is_approved=True).select_related("user")
    can_review, has_reviewed = False, False
    if request.user.is_authenticated:
        has_reviewed = reviews.filter(user=request.user).exists()
        can_review = not has_reviewed and OrderItem.objects.filter(
            order__user=request.user, product=product, order__status__in=[Order.Status.DELIVERED, Order.Status.COMPLETED]
        ).exists()
    distribution = {i: reviews.filter(rating=i).count() for i in range(5, 0, -1)}
    in_wishlist = request.user.is_authenticated and Wishlist.objects.filter(user=request.user, product=product).exists()
    return render(
        request,
        "catalog/detail.html",
        {
            "product": product,
            "images": product.images.all(),
            "reviews": reviews[:20],
            "distribution": distribution,
            "review_form": ReviewForm() if can_review else None,
            "has_reviewed": has_reviewed,
            "in_wishlist": in_wishlist,
            "bought_together": engine.frequently_bought_together(product),
            "similar": engine.hybrid_for_product(product),
            "recently_viewed": engine.recently_viewed(request, exclude=product.pk),
        },
    )


@login_required_post(lambda request, slug: reverse("catalog:detail", args=[slug]) + "#reviews")
def add_review(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    purchased = OrderItem.objects.filter(
        order__user=request.user, product=product, order__status__in=[Order.Status.DELIVERED, Order.Status.COMPLETED]
    ).exists()
    if not purchased:
        messages.error(request, "Chỉ khách đã nhận hàng mới có thể đánh giá sản phẩm.")
        return redirect(product)
    form = ReviewForm(request.POST)
    if form.is_valid():
        Review.objects.update_or_create(
            product=product, user=request.user, defaults={**form.cleaned_data, "is_verified_purchase": True}
        )
        messages.success(request, "Cảm ơn bạn đã đánh giá!")
    else:
        messages.error(request, "Đánh giá chưa hợp lệ, vui lòng kiểm tra lại.")
    return redirect(product.get_absolute_url() + "#reviews")


@login_required_post(lambda request, product_id: get_object_or_404(Product, pk=product_id).get_absolute_url())
def toggle_wishlist(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    obj, created = Wishlist.objects.get_or_create(user=request.user, product=product)
    if not created:
        obj.delete()
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"in_wishlist": created})
    messages.success(request, "Đã thêm vào danh sách yêu thích." if created else "Đã bỏ khỏi danh sách yêu thích.")
    return redirect(safe_next(request, product.get_absolute_url()))


@login_required
def wishlist(request):
    items = list(Wishlist.objects.filter(user=request.user).select_related("product"))
    # Re-fetch the products with their rating annotation so the cards match the rest of the shop.
    rated = Product.objects.filter(pk__in=[w.product_id for w in items]).select_related("brand").prefetch_related("images").with_ratings().in_bulk()
    for w in items:
        w.product = rated.get(w.product_id, w.product)
    return render(request, "catalog/wishlist.html", {"items": items})


@require_GET
def autocomplete(request):
    """Search-box suggestions: the matching categories (with counts) and a few popular products taken in turn
    from each of them, so a brand search shows its mice as well as its webcams."""
    raw = request.GET.get("q", "").strip()[:60]
    q = strip_accents(raw)
    if len(q) < 2:
        return JsonResponse({"results": [], "categories": [], "total": 0, "all_url": ""})
    qs = Product.objects.active()
    for t in q.split():
        qs = qs.filter(search_text__icontains=t)
    counts, cats, order = categories_by_matches(qs)
    pool = defaultdict(list)
    for p in qs.select_related("category").prefetch_related("images").order_by("-sold_count", "-view_count", "-id")[:60]:
        pool[p.category_id].append(p)
    picks = []
    while len(picks) < 6 and any(pool.values()):
        for c in order:
            if pool[c] and len(picks) < 6:
                picks.append(pool[c].pop(0))
    query = "?" + urlencode({"q": raw})
    return JsonResponse({
        "results": [
            {
                "name": p.name,
                "url": p.get_absolute_url(),
                "price": p.current_price,
                "category": p.category.name,
                "image": p.main_image.image.url if p.main_image else "",
            }
            for p in picks
        ],
        "categories": [{"name": cats[c].name, "count": counts[c], "url": cats[c].get_absolute_url() + query} for c in order],
        "total": sum(counts.values()),
        "all_url": reverse("catalog:list") + query,
    })


def compare(request):
    ids = [i for i in request.GET.get("ids", "").split(",") if i.isdigit()][:4]
    products = list(Product.objects.active().filter(pk__in=ids).select_related("brand", "category").prefetch_related("images").with_ratings())
    products.sort(key=lambda p: ids.index(str(p.pk)))
    keys = []
    for p in products:
        p.compare_without = ",".join(str(o.pk) for o in products if o.pk != p.pk)
        for k in p.specs:
            if k not in keys:
                keys.append(k)
    return render(request, "catalog/compare.html", {"products": products, "spec_keys": keys})
