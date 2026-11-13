"""Product-listing sidebar (category switcher, no brand/need filters) and the home-page banner carousel."""
import html
import re

from django.test import override_settings
from django.urls import reverse

from apps.catalog.models import Category, Product
from apps.pages.models import Banner

from .test_shop import BaseShopTest


class ListingSidebarTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.headset = Category.objects.create(name="Tai nghe", slug="tai-nghe", icon="headset")

    def get(self, slug=None, **params):
        url = reverse("catalog:category", args=[slug]) if slug else reverse("catalog:list")
        return self.client.get(url, params)

    def sidebar(self, r):
        html = r.content.decode()
        return html[html.index('<aside class="filters"'):html.index("</aside>")]

    def test_category_page_links_to_every_other_category(self):
        side = self.sidebar(self.get("chuot"))
        for slug in ("lot-chuot", "tai-nghe"):
            self.assertIn(f'href="{reverse("catalog:category", args=[slug])}', side)
        self.assertIn(f'href="{reverse("catalog:list")}', side)  # "Tất cả sản phẩm"
        current = re.search(r'<a href="([^"]*)" class="active" aria-current="page">', side)
        self.assertEqual(current.group(1).split("?")[0], reverse("catalog:category", args=["chuot"]))

    def test_all_products_page_marks_all_as_current(self):
        side = self.sidebar(self.get())
        current = re.search(r'<a href="([^"]*)" class="active" aria-current="page">', side)
        self.assertEqual(current.group(1).split("?")[0], reverse("catalog:list"))

    def test_no_brand_or_need_filter(self):
        side = self.sidebar(self.get("chuot"))
        self.assertNotIn("Thương hiệu", side)
        self.assertNotIn("Nhu cầu", side)
        self.assertNotIn('type="checkbox" name="brand"', side)
        self.assertNotIn('type="radio" name="tag"', side)
        self.assertIn('name="price"', side)  # the other filters stay

    def test_switching_category_keeps_price_and_sort_but_drops_brand_tag_and_page(self):
        side = self.sidebar(self.get("chuot", price="0-500000", sort="price_asc", tag="fps", brand="logitech-g", page="2"))
        link = re.search(r'href="(%s[^"]*)"' % re.escape(reverse("catalog:category", args=["tai-nghe"])), side).group(1)
        self.assertIn("price=0-500000", link)
        self.assertIn("sort=price_asc", link)
        for gone in ("tag=", "brand=", "page="):
            self.assertNotIn(gone, link)

    def test_tag_from_a_home_tile_still_filters_and_shows_a_removable_chip(self):
        r = self.get(tag="moba")
        self.assertEqual([p.name for p in r.context["page"]], ["Logitech G640 Bàn di"])
        self.assertContains(r, "Setup MOBA")
        self.assertContains(r, 'name="tag" value="moba"')  # kept when price / stock filters change
        self.assertContains(r, 'class="pill" href="?"')  # the chip's link clears the tag

    def test_brand_link_from_a_product_page_shows_a_chip(self):
        r = self.get(brand=self.m1.brand.slug)
        self.assertContains(r, "Thương hiệu: Logitech G")
        self.assertEqual(r.context["page"].paginator.count, 3)

    def test_filters_apply_on_change_without_apply_or_clear_buttons(self):
        side = self.sidebar(self.get("chuot"))
        self.assertIn("data-auto-submit", side)
        self.assertNotIn("Áp dụng", side)
        self.assertNotIn("Xoá lọc", side)
        self.assertIn("<noscript>", side)  # a submit button only for browsers without JavaScript


class SearchAcrossCategoriesTests(BaseShopTest):
    """Searching a brand must show every kind of product it makes, not only the first page of one kind."""

    def setUp(self):
        super().setUp()
        brand, mouse = self.m1.brand, self.m1.category
        headset = Category.objects.create(name="Tai nghe", slug="tai-nghe", icon="headset", sort_order=2)
        for i in range(6):  # 8 Logitech mice in all, more than one group shows
            Product.objects.create(category=mouse, brand=brand, name=f"Logitech G Mouse {i}", sku=f"MX{i}", price=1_000_000, stock=1, sold_count=100 + i)
        self.h1 = Product.objects.create(category=headset, brand=brand, name="Logitech G733", sku="H1", price=2_000_000, stock=1)

    def search(self, slug=None, **params):
        url = reverse("catalog:category", args=[slug]) if slug else reverse("catalog:list")
        return self.client.get(url, {"q": "logitech", **params})

    def test_results_are_grouped_per_category_biggest_first(self):
        r = self.search()
        groups = r.context["groups"]
        self.assertEqual([(g["category"].slug, g["count"]) for g in groups], [("chuot", 8), ("lot-chuot", 1), ("tai-nghe", 1)])
        self.assertEqual(len(groups[0]["products"]), 5)
        self.assertEqual(groups[0]["more"], 3)
        self.assertContains(r, "10 sản phẩm trong 3 danh mục")
        self.assertContains(r, "Logitech G733")  # the lone headset is not pushed off the page by the mice
        self.assertNotContains(r, 'class="pagination')

    def test_see_more_opens_the_category_with_the_same_search(self):
        r = self.search(sort="price_asc", page="2")
        self.assertContains(r, "Xem thêm 3 sản phẩm")
        more = html.unescape(re.search(r'<a class="section-more" href="([^"]+)">Xem thêm 3', r.content.decode()).group(1))
        self.assertTrue(more.startswith(reverse("catalog:category", args=["chuot"]) + "?"))
        self.assertIn("q=logitech", more)
        self.assertIn("sort=price_asc", more)
        self.assertNotIn("page=", more)
        self.assertEqual(self.client.get(more).context["page"].paginator.count, 8)

    def test_groups_follow_the_chosen_sort(self):
        cheapest = self.search(sort="price_asc").context["groups"][0]["products"]
        self.assertEqual(cheapest[0], self.m1)  # 750.000₫ on sale

    def test_search_inside_a_category_or_with_a_single_category_is_a_plain_grid(self):
        self.assertEqual(self.search("chuot").context["groups"], [])
        r = self.client.get(reverse("catalog:list"), {"q": "mouse"})
        self.assertEqual(r.context["groups"], [])
        self.assertEqual(r.context["page"].paginator.count, 6)

    def test_autocomplete_mixes_categories_and_counts_them(self):
        d = self.client.get(reverse("catalog:autocomplete"), {"q": "Logitech"}).json()
        self.assertEqual(len(d["results"]), 6)
        self.assertEqual({p["category"] for p in d["results"]}, {"Chuột gaming", "Lót chuột", "Tai nghe"})
        self.assertEqual([(c["name"], c["count"]) for c in d["categories"]], [("Chuột gaming", 8), ("Lót chuột", 1), ("Tai nghe", 1)])
        self.assertEqual(d["categories"][0]["url"], reverse("catalog:category", args=["chuot"]) + "?q=Logitech")
        self.assertEqual(d["total"], 10)
        self.assertEqual(d["all_url"], reverse("catalog:list") + "?q=Logitech")


class HeroCarouselTests(BaseShopTest):
    def test_one_shared_row_of_dots_one_per_banner(self):
        for i, theme in enumerate(("violet", "lime", "cyan")):
            Banner.objects.create(title=f"Banner {i}", theme=theme, sort_order=i)
        html = self.client.get(reverse("pages:home")).content.decode()
        self.assertEqual(html.count("data-slide"), 3)
        self.assertEqual(html.count("data-hero-dots"), 1)
        dots = html[html.index("data-hero-dots"):]
        dots = dots[:dots.index("</div>")]
        self.assertEqual(dots.count("<button"), 3)
        self.assertEqual(dots.count('aria-current="true"'), 1)

    def test_single_banner_has_no_dots(self):
        Banner.objects.create(title="Only one")
        self.assertNotContains(self.client.get(reverse("pages:home")), "data-hero-dots")

    @override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                                 "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
    def test_dev_assets_are_versioned_so_browsers_reload_them(self):
        html = self.client.get(reverse("pages:home")).content.decode()
        self.assertRegex(html, r'src="/static/js/main\.js\?v=\d+"')
        self.assertRegex(html, r'href="/static/css/main\.css\?v=\d+"')
