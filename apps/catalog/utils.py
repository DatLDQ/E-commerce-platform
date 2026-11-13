import re
import unicodedata


def strip_accents(text: str) -> str:
    """'Bàn phím cơ' -> 'ban phim co' — makes Vietnamese search accent-insensitive."""
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip().lower()


def vnd(value) -> str:
    try:
        return f"{int(value):,}".replace(",", ".") + "₫"
    except (TypeError, ValueError):
        return ""
