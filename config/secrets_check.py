"""Refuse to run a production (DEBUG=False) site with placeholder secrets.

Kept free of Django imports so settings.py can call it at import time — that
way gunicorn fails to boot instead of silently serving with a known key.
"""

PLACEHOLDER_MARKERS = ("change-me", "changeme", "dev-only", "insecure", "placeholder")
MIN_SECRET_LENGTH = 32


def weak_secret(value: str) -> bool:
    value = value or ""
    return len(value) < MIN_SECRET_LENGTH or any(m in value.lower() for m in PLACEHOLDER_MARKERS)


def insecure_settings(*, debug: bool, secret_key: str, allow_mock_payments: bool, mock_gateway_secret: str) -> list[str]:
    """Return a list of human-readable problems (empty = OK)."""
    if debug:
        return []
    problems = []
    if weak_secret(secret_key):
        problems.append(f"DJANGO_SECRET_KEY is missing or a placeholder (need ≥{MIN_SECRET_LENGTH} random characters).")
    if allow_mock_payments and weak_secret(mock_gateway_secret):
        problems.append(
            "ALLOW_MOCK_PAYMENTS is on but MOCK_GATEWAY_SECRET is missing or a placeholder — anyone could forge "
            f"a 'paid' callback. Set ≥{MIN_SECRET_LENGTH} random characters or turn ALLOW_MOCK_PAYMENTS off."
        )
    return problems
