from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.catalog.models import Category, Product


class ProductSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        return Product.objects.active()

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(Sitemap):
    priority = 0.6

    def items(self):
        return Category.objects.all()


class StaticSitemap(Sitemap):
    priority = 0.4

    def items(self):
        return ["pages:home", "pages:about", "pages:contact", "pages:faq", "catalog:list"]

    def location(self, item):
        return reverse(item)
