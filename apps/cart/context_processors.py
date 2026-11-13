from .services import get_cart


def cart(request):
    # Error pages (404/500) can be rendered for requests that never went through
    # SessionMiddleware/AuthenticationMiddleware — don't turn them into a crash.
    if not hasattr(request, "user") or not hasattr(request, "session"):
        return {"cart_count": 0}
    c = get_cart(request)
    return {"cart_count": c.total_quantity if c else 0}
