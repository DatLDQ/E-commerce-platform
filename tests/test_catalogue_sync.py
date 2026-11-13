"""seed_demo --sync, the real product photos and the photo-credits page."""
import io
import shutil
import tempfile
from unittest import mock

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils.text import slugify

from apps.accounts.models import User
from apps.catalog.management.commands import seed_demo
from apps.catalog.models import Brand, Product, ProductImage
from apps.orders.models import OrderItem
from apps.pages.models import Banner

from .test_shop import BaseShopTest

ROWS = [
    ("chuot", "Razer", "Test Sync Mouse", 990000, None, 10, "fps", 12, 100, {"DPI": "1600"}, "Chuột test."),
    ("tai-nghe", "Razer", "Test Sync Headset", 1990000, 1490000, 5, "wireless", 12, 300, {"Driver": "40 mm"}, "Tai nghe test."),
]


class CatalogueDataTests(SimpleTestCase):
    """The shipped catalogue: one real photo per product, credited, nothing left over."""

    def test_every_product_has_its_own_photo(self):
        for row in seed_demo.P:
            with self.subTest(product=row[2]):
                data = seed_demo.demo_photo(row[2])
                self.assertIsNotNone(data, "a product without an exact photo must not be in the catalogue")
                self.assertTrue(data.startswith(b"\xff\xd8"))

    def test_every_photo_is_credited_and_none_is_unused(self):
        slugs = {slugify(row[2]) for row in seed_demo.P}
        credits = seed_demo.photo_credits()
        self.assertEqual({k[2:] for k in credits if k.startswith("p:")}, slugs)
        self.assertEqual({f.stem for f in seed_demo.PHOTO_DIR.glob("*.jpg")}, slugs)

    def test_names_are_unique_and_brands_known(self):
        names = [row[2] for row in seed_demo.P]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual({row[1] for row in seed_demo.P}, set(seed_demo.BRANDS))
        self.assertFalse(set(seed_demo.RETIRED) & set(names))

    def test_banner_copy_matches_the_catalogue(self):
        """“giảm đến 20%” and “giá từ 2,99 triệu” on the home page must be true of the shipped catalogue."""
        self.assertLessEqual(max(1 - r[4] / r[3] for r in seed_demo.P if r[4]), 0.2)
        self.assertEqual(min(r[4] or r[3] for r in seed_demo.P if r[0] == "man-hinh"), 2990000)


class CatalogueSyncTests(BaseShopTest):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        User.objects.create_user("buyer1", "b1@example.com", "x-Strong-Pass-1")
        User.objects.create_user("buyer2", "b2@example.com", "x-Strong-Pass-2")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def sync(self, photo=b"\xff\xd8PHOTO", retired=()):
        with mock.patch.object(seed_demo, "P", ROWS), mock.patch.object(seed_demo, "RETIRED", list(retired)), \
                mock.patch.object(seed_demo, "BRANDS", {"Razer": "Mỹ"}), mock.patch.object(seed_demo, "demo_photo", return_value=photo):
            out = io.StringIO()
            call_command("seed_demo", "--sync", stdout=out)
        return out.getvalue()

    @staticmethod
    def content(img):
        with img.image.open("rb") as f:
            return f.read()

    def test_sync_adds_missing_products_once_with_one_photo_and_reviews(self):
        before = Product.objects.count()
        self.sync()
        self.assertEqual(Product.objects.count(), before + 2)
        p = Product.objects.get(name="Test Sync Mouse")
        self.assertEqual(p.images.count(), 1)
        self.assertGreater(p.reviews.count(), 0)
        self.assertGreater(Product.objects.with_ratings().get(pk=p.pk).avg_rating, 0)
        self.sync()  # idempotent
        self.assertEqual(Product.objects.count(), before + 2)
        self.assertEqual(p.images.count(), 1)

    def test_sync_fills_blank_banner_labels(self):
        b = Banner.objects.create(title="Old banner", theme="cyan", cta_url="/", cta_text="Xem")
        self.sync()
        b.refresh_from_db()
        self.assertEqual(b.kicker, seed_demo.BANNER_KICKERS["cyan"])

    def test_sync_renames_an_outdated_banner_instead_of_adding_one(self):
        old, new = next(iter(seed_demo.BANNER_RENAMED.items()))
        b = Banner.objects.create(title=old, subtitle="Màn 165Hz", theme="cyan", kicker="Màn hình mới", cta_url="/", cta_text="Xem")
        self.sync()
        b.refresh_from_db()
        self.assertEqual(b.title, new)
        self.assertEqual(Banner.objects.filter(title=new).count(), 1)
        self.assertEqual(b.subtitle, next(x["subtitle"] for x in seed_demo.BANNERS if x["title"] == new))
        self.assertEqual(b.kicker, seed_demo.BANNER_KICKERS["cyan"])

    def test_sync_refreshes_specs_of_existing_products_but_not_price_or_stock(self):
        self.sync()
        p = Product.objects.get(name="Test Sync Mouse")
        Product.objects.filter(pk=p.pk).update(specs={"DPI": "800"}, short_description="Mô tả cũ", price=123000, stock=1)
        self.sync()
        p.refresh_from_db()
        self.assertEqual((p.specs, p.short_description), ({"DPI": "1600"}, "Chuột test."))
        self.assertEqual((p.price, p.stock), (123000, 1))
        self.assertIn("chuot test", p.search_text.lower())

    def test_sync_replaces_photo_drops_generated_art_and_keeps_admin_uploads(self):
        self.sync(photo=b"PHOTO-1")
        p = Product.objects.get(name="Test Sync Mouse")
        art = ProductImage.objects.create(product=p, sort_order=1, image=ContentFile(b"ART", name=f"{p.slug}-1.jpg"))
        mine = ProductImage.objects.create(product=p, sort_order=2, image=ContentFile(b"MINE", name="my-upload.jpg"))
        self.sync(photo=b"PHOTO-2")  # a newer demo photo replaces the older one
        self.assertFalse(ProductImage.objects.filter(pk=art.pk).exists())
        self.assertEqual(self.content(p.images.get(sort_order=0)), b"PHOTO-2")
        mine.refresh_from_db()
        self.assertEqual(self.content(mine), b"MINE")

    def test_sync_retires_old_demo_products_but_orders_keep_their_lines(self):
        self.add(self.m1)
        self.checkout()
        line = OrderItem.objects.get(product=self.m1)
        self.sync(retired=[self.m1.name])
        self.assertFalse(Product.objects.filter(pk=self.m1.pk).exists())
        line.refresh_from_db()
        self.assertIsNone(line.product)
        self.assertEqual((line.product_name, line.sku), (self.m1.name, "M1"))
        self.assertTrue(Product.objects.filter(pk=self.m2.pk).exists())  # not retired, not in the catalogue: untouched

    def test_sync_removes_brands_without_products(self):
        Brand.objects.create(name="Ghost Brand")
        self.sync()
        self.assertFalse(Brand.objects.filter(name="Ghost Brand").exists())
        self.assertTrue(Brand.objects.filter(name="Logitech G").exists())

    def test_sync_takes_the_next_free_sku_when_an_older_product_holds_it(self):
        Product.objects.filter(pk=self.m1.pk).update(sku="LU-CHU-001")
        self.sync()
        self.assertEqual(Product.objects.get(name="Test Sync Mouse").sku, "LU-CHU-002")

    def test_lost_files_are_restored_from_the_photo_or_removed(self):
        main = ProductImage.objects.create(product=self.m1, sort_order=0, image=ContentFile(b"OLD", name=f"{self.m1.slug}-photo.jpg"))
        extra = ProductImage.objects.create(product=self.m1, sort_order=1, image=ContentFile(b"ART", name=f"{self.m1.slug}-1.jpg"))
        for img in (main, extra):
            img.image.storage.delete(img.image.name)
        with mock.patch.object(seed_demo, "demo_photo", return_value=b"PHOTO"):
            call_command("seed_demo", stdout=io.StringIO())
        main.refresh_from_db()
        self.assertEqual(self.content(main), b"PHOTO")
        self.assertFalse(ProductImage.objects.filter(pk=extra.pk).exists())


class PhotoCreditsPageTests(BaseShopTest):
    def test_lists_every_credit(self):
        credits = {"p:x": {"used_for": "Test Sync Mouse", "title": "A mouse", "creator": "Jane", "creator_url": "",
                           "license": "CC BY 2.0", "license_url": "https://creativecommons.org/licenses/by/2.0/",
                           "source_url": "https://example.org/photo", "group": "1-product"}}
        with mock.patch.object(seed_demo, "photo_credits", return_value=credits):
            r = self.client.get(reverse("pages:credits"))
        self.assertContains(r, "Test Sync Mouse")
        self.assertContains(r, "CC BY 2.0")
        self.assertContains(r, "https://example.org/photo")

    def test_footer_links_to_credits(self):
        self.assertContains(self.client.get(reverse("pages:home")), reverse("pages:credits"))
