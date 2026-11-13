from django.core.cache import cache

from .models import Category


def navigation(request):
    cats = cache.get("nav_categories")
    if cats is None:
        cats = list(Category.objects.all())
        cache.set("nav_categories", cats, 300)
    return {"nav_categories": cats}
