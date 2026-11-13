import os
from urllib.parse import urlencode

from django import template
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import ManifestFilesMixin, staticfiles_storage
from django.templatetags.static import static

from ..utils import vnd as _vnd

register = template.Library()


@register.simple_tag
def asset(path):
    """{% asset 'js/main.js' %}: the static URL, versioned so browsers pick up edits.

    The production storage already puts a content hash in the file name; in development the plain
    name is served without Cache-Control, so browsers keep running an old copy. Append ?v=<mtime>.
    """
    url = static(path)
    if not isinstance(staticfiles_storage, ManifestFilesMixin):
        found = finders.find(path)
        if found:
            url += f"?v={int(os.path.getmtime(found))}"
    return url


@register.filter
def vnd(value):
    """{{ 1290000|vnd }} -> 1.290.000₫"""
    return _vnd(value)


@register.filter
def stars(value):
    """Return a list of 'full'/'half'/'empty' for 5 star icons."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0
    out = []
    for i in range(1, 6):
        out.append("full" if v >= i else "half" if v >= i - 0.5 else "empty")
    return out


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    """Keep current filters when changing one GET param (pagination, sort…)."""
    q = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            q.pop(k, None)
        else:
            q[k] = v
    q.pop("page", None) if "page" not in kwargs else None
    return "?" + urlencode(q, doseq=True)


@register.filter
def get_item(d, key):
    return d.get(key) if hasattr(d, "get") else None


@register.filter
def qty_max(product):
    """Upper bound for a quantity input: what one order may hold (stock, capped by the per-line limit)."""
    from apps.cart.services import max_quantity

    return max_quantity(product)


@register.filter
def unique_messages(messages):
    """Show a notice once even if the same action queued it twice (e.g. a double-submitted form)."""
    seen, out = set(), []
    for m in messages:
        key = (m.level, str(m))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out
