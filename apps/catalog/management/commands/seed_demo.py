"""python manage.py seed_demo [--reset] [--orders N]

Builds a realistic demo dataset:
  * 8 categories, the brands that have products, gaming products with specs and one real photo each
    (a model without an exact, openly-licensed photo is simply not in the catalogue)
  * delivery methods, coupons, banners, chatbot FAQ
  * 1 staff account + 1 demo customer + ~140 customers registered over 6 months
  * ~700 orders over 180 days with growth trend and co-purchase patterns
    (so the dashboard KPIs and the recommendation engine have real signal)
  * reviews, product views, site visits, search logs, chatbot transcripts
"""
import json
import os
import random
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Address, User
from apps.catalog.models import Brand, Category, Product, ProductImage, Review
from apps.chatbot.models import FAQ, ChatMessage
from apps.orders.models import Coupon, DeliveryMethod, Order, OrderItem, OrderStatusHistory
from apps.orders.services import PROVINCES
from apps.pages.models import Banner
from apps.payments.models import Payment
from apps.recommendations import engine
from apps.recommendations.models import ProductView, SearchLog, SiteVisit

# Photos of the exact product model (CC0 / CC BY / CC BY-SA, from Wikimedia Commons and Flickr). File name = slugify(product name).
# Attribution for every file lives in credits.json and is shown on /nguon-anh/.
PHOTO_DIR = Path(__file__).resolve().parents[2] / "demo_photos"


def demo_photo(name):
    """JPEG bytes of the photo of this exact product, or None."""
    path = PHOTO_DIR / f"{slugify(name)}.jpg"
    return path.read_bytes() if path.exists() else None


def photo_credits():
    path = PHOTO_DIR / "credits.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def seed_owned(img):
    """True for an image file the seed wrote ("<slug>-photo.jpg", or "<slug>-0/1.jpg" art from older seeds), never an admin upload."""
    return bool(re.fullmatch(rf"{re.escape(img.product.slug)}-(\d+|photo)(_\w+)?\.jpg", img.image.name.rsplit("/", 1)[-1]))


BANNER_KICKERS = {"violet": "LevelUp Week", "lime": "Setup FPS", "cyan": "Màn hình gaming"}
# Home-page carousel. The copy must match the catalogue (the cheapest monitor, the fastest refresh rate, the biggest discount).
BANNERS = [
    dict(theme="violet", title="LevelUp Week — giảm đến 20% gear esports", cta_url="/san-pham/?on_sale=1", cta_text="Săn sale ngay",
         subtitle="Chuột, bàn phím, tai nghe chính hãng. Nhập LEVELUP15 giảm thêm 15% (tối đa 500K) cho đơn từ 2 triệu."),
    dict(theme="lime", title="Setup FPS chuẩn pro dưới 5 triệu", cta_url="/san-pham/?tag=fps", cta_text="Xem setup FPS",
         subtitle="Combo chuột siêu nhẹ + pad cứng tốc độ + tai nghe nghe chân — LevelBot tư vấn theo ngân sách của bạn."),
    dict(theme="cyan", title="Màn hình tới 144Hz, giá từ 2,99 triệu", cta_url="/san-pham/danh-muc/man-hinh/", cta_text="Chọn màn hình",
         subtitle="Từ màn 24\" 120Hz cho esports đến ultrawide 34\" cong — thấy địch trước khi địch thấy bạn."),
]
# Titles used by earlier seeds -> current title, so `--sync` updates those banners instead of adding a second one.
BANNER_RENAMED = {"Màn hình 165–180Hz giá từ 2,99 triệu": "Màn hình tới 144Hz, giá từ 2,99 triệu"}
# Earlier banner copy -> current copy. Applied on every start, but only where the text was never edited in the admin.
BANNER_SUBTITLE_FIXES = {
    "Chuột, bàn phím, tai nghe chính hãng. Nhập LEVELUP15 giảm thêm 15% cho đơn từ 2 triệu.": "Chuột, bàn phím, tai nghe chính hãng. Nhập LEVELUP15 giảm thêm 15% (tối đa 500K) cho đơn từ 2 triệu.",
}

# Well-known demo passwords (printed in the README). Only ever used with DEBUG=True:
# a public deployment must take the staff password from DJANGO_SUPERUSER_PASSWORD.
DEMO_ADMIN_PASSWORD = "Admin@12345"
DEMO_CUSTOMER_PASSWORD = "Demo@12345"

CATEGORIES = [
    ("chuot", "Chuột gaming", "mouse", "Chuột siêu nhẹ, cảm biến chính xác cho FPS và MOBA."),
    ("ban-phim", "Bàn phím cơ", "keyboard", "Bàn phím cơ hot-swap, switch đa dạng, LED RGB."),
    ("tai-nghe", "Tai nghe", "headset", "Âm thanh vòm, mic khử ồn — nghe rõ từng bước chân."),
    ("man-hinh", "Màn hình", "monitor", "Màn hình gaming 100–144Hz, từ 24\" esports đến ultrawide cong 34\"."),
    ("ghe-gaming", "Ghế gaming", "chair", "Ghế công thái học cho những phiên rank dài."),
    ("lot-chuot", "Lót chuột", "pad", "Pad cứng tốc độ và pad vải cho game FPS."),
    ("tay-cam", "Tay cầm & vô lăng", "gamepad", "Tay cầm PC/console, vô lăng đua xe và joystick bay."),
    ("micro-stream", "Micro & Stream", "mic", "Micro, webcam, capture card và Stream Deck cho streamer."),
]

# Only brands that have at least one product in P (a test keeps the two in step).
BRANDS = {
    "Logitech G": "Thuỵ Sĩ", "Razer": "Mỹ / Singapore", "SteelSeries": "Đan Mạch", "Roccat": "Đức", "Corsair": "Mỹ",
    "Keychron": "Hồng Kông", "Das Keyboard": "Mỹ", "Creative": "Singapore", "MSI": "Đài Loan",
    "Dell": "Mỹ", "AORUS": "Đài Loan", "BenQ": "Đài Loan", "Thermaltake": "Đài Loan", "Microsoft": "Mỹ", "Sony": "Nhật Bản",
    "Nintendo": "Nhật Bản", "8BitDo": "Trung Quốc", "Thrustmaster": "Pháp", "Turtle Beach": "Mỹ", "Valve": "Mỹ",
    "Blue Microphones": "Mỹ", "Shure": "Mỹ", "Rode": "Úc", "Audio-Technica": "Nhật Bản", "Elgato": "Đức",
    "Focusrite": "Anh", "AVerMedia": "Đài Loan",
}

# (category, brand, name, price, sale_price|None, stock, tags, warranty, weight_g, specs, short)
# Every row has a photo of that exact model in demo_photos/ — a model without one is not sold here.
P = [
    # ---- Chuột gaming
    ("chuot", "Logitech G", "Logitech G Pro X Superlight 2", 3290000, 2890000, 34, "fps,wireless,lightweight,esports", 24, 300,
     {"Cảm biến": "HERO 2", "DPI tối đa": "32.000", "Trọng lượng": "60 g", "Kết nối": "LIGHTSPEED 2.4GHz", "Pin": "95 giờ", "Màu": "Magenta"},
     "Chuột không dây 60g được tuyển thủ CS2 & Valorant tin dùng."),
    ("chuot", "Logitech G", "Logitech G403", 990000, 890000, 40, "fps,moba,rgb", 24, 250,
     {"Cảm biến": "PMW3366", "DPI tối đa": "12.000", "Trọng lượng": "87 g (+10 g tạ)", "Kết nối": "Có dây", "LED": "RGB 2 vùng"},
     "Form công thái học vừa tay, cảm biến chuẩn esports."),
    ("chuot", "Logitech G", "Logitech G502 Proteus Core", 1190000, 990000, 26, "moba,fps,rgb", 24, 320,
     {"Cảm biến": "PMW3366", "DPI tối đa": "12.000", "Nút lập trình": "11", "Tạ chỉnh": "5 × 3,6 g", "Kết nối": "Có dây"},
     "G502 đời đầu: 11 nút, bộ tạ chỉnh trọng lượng, cuộn siêu tốc."),
    ("chuot", "Logitech G", "Logitech G305 Lightspeed", 890000, 749000, 80, "fps,wireless,budget", 24, 200,
     {"Cảm biến": "HERO", "DPI tối đa": "12.000", "Trọng lượng": "99 g", "Kết nối": "LIGHTSPEED 2.4GHz", "Pin": "250 giờ (1 pin AA)"},
     "Chuột không dây quốc dân, pin cực lâu."),
    ("chuot", "Logitech G", "Logitech G903 Lightspeed", 2990000, 2490000, 12, "moba,wireless,rgb,premium", 24, 330,
     {"Cảm biến": "HERO 25K", "Nút lập trình": "11", "Trọng lượng": "110 g", "Kết nối": "LIGHTSPEED / có dây", "Sạc": "Tương thích POWERPLAY"},
     "Chuột không dây thuận cả hai tay, nút bên tháo lắp được."),
    ("chuot", "Logitech G", "Logitech G600 MMO", 1090000, None, 18, "moba,mmo,rgb", 24, 300,
     {"DPI tối đa": "8.200", "Nút lập trình": "20", "Phím G-Shift": "Có", "Kết nối": "Có dây"},
     "12 phím ngón cái cho MMO, gán macro không giới hạn."),
    ("chuot", "Logitech G", "Logitech G402 Hyperion Fury", 590000, None, 45, "fps,budget", 24, 250,
     {"Cảm biến": "Fusion Engine", "DPI tối đa": "4.000", "Tốc độ": "500 IPS", "Nút lập trình": "8", "Trọng lượng": "108 g"},
     "Chuột FPS tốc độ cao giá dễ chịu."),
    ("chuot", "Logitech G", "Logitech G700", 1290000, None, 9, "moba,wireless", 24, 300,
     {"Cảm biến": "Laser", "DPI tối đa": "5.700", "Nút lập trình": "13", "Kết nối": "Không dây / có dây", "Pin": "1 pin AA sạc"},
     "Chuột không dây 13 nút, dùng được cả khi đang sạc."),
    ("chuot", "Logitech G", "Logitech G703", 1890000, 1590000, 21, "fps,wireless,rgb", 24, 260,
     {"Kết nối": "LIGHTSPEED / có dây", "Trọng lượng": "95 g (+10 g tạ)", "LED": "LIGHTSYNC RGB", "Sạc": "Tương thích POWERPLAY"},
     "Bản không dây của form G403, độ trễ như có dây."),
    ("chuot", "Razer", "Razer DeathAdder Elite", 990000, 799000, 50, "fps,esports,rgb", 24, 260,
     {"Cảm biến": "Optical 5G", "DPI tối đa": "16.000", "Tốc độ": "450 IPS", "Switch": "Razer Mechanical 50 triệu lần nhấn", "Trọng lượng": "105 g"},
     "Thiết kế công thái học huyền thoại của Razer."),
    ("chuot", "Razer", "Razer DeathAdder V2 Pro", 2490000, 2090000, 17, "fps,wireless,esports", 24, 260,
     {"Cảm biến": "Focus+ 20K", "Trọng lượng": "88 g", "Kết nối": "HyperSpeed / Bluetooth / có dây", "Pin": "70 giờ (HyperSpeed)", "Switch": "Optical"},
     "DeathAdder không dây, switch quang học nhạy."),
    ("chuot", "Razer", "Razer Basilisk V3", 1690000, None, 22, "moba,fps,rgb", 24, 300,
     {"Cảm biến": "Focus+ 26K", "Nút lập trình": "11", "Con lăn": "HyperScroll Tilt", "LED": "Chroma RGB 11 vùng"},
     "Chuột 11 nút cho MOBA/MMO, LED Chroma 11 vùng."),
    ("chuot", "Razer", "Razer Naga Chroma", 1490000, 1290000, 14, "moba,mmo,rgb", 24, 300,
     {"Cảm biến": "Laser 5G", "DPI tối đa": "16.000", "Nút ngón cái": "12 (cơ học)", "Nút lập trình": "19", "LED": "Chroma RGB"},
     "Chuột MMO 12 nút ngón cái cơ học, LED Chroma."),
    ("chuot", "Razer", "Razer Ouroboros", 2190000, 1790000, 7, "moba,wireless", 24, 350,
     {"Cảm biến": "Laser 4G", "DPI tối đa": "8.200", "Kết nối": "Không dây / có dây", "Thiết kế": "Thuận 2 tay, chỉnh độ dài & lưng tì"},
     "Chuột chỉnh được form lưng và độ dài theo bàn tay."),
    ("chuot", "Razer", "Razer Imperator", 990000, None, 11, "fps", 24, 260,
     {"Cảm biến": "Laser 4G", "DPI tối đa": "6.400", "Nút lập trình": "7", "Nút bên": "Trượt chỉnh vị trí"},
     "Cụm nút bên trượt được để vừa ngón cái."),
    ("chuot", "Razer", "Razer Abyssus V2", 490000, None, 60, "fps,budget,lightweight", 24, 200,
     {"Cảm biến": "Optical", "DPI tối đa": "5.000", "Thiết kế": "Đối xứng", "Nút": "3"},
     "Chuột đối xứng gọn nhẹ, đủ dùng cho FPS."),
    ("chuot", "Razer", "Razer Mamba Tournament Edition", 1490000, None, 12, "fps,moba,rgb", 24, 300,
     {"Cảm biến": "Laser 5G", "DPI tối đa": "16.000", "Kết nối": "Có dây", "Nút lập trình": "9", "LED": "Chroma RGB"},
     "Bản có dây của Mamba dành cho thi đấu, chỉnh được lực nhấn."),
    ("chuot", "Razer", "Razer Naga Hex League of Legends Edition", 1190000, None, 8, "moba", 24, 300,
     {"Cảm biến": "Laser", "DPI tối đa": "5.600", "Nút ngón cái": "6 (bố trí lục giác)", "Phiên bản": "League of Legends"},
     "Bánh xe 6 nút ngón cái cho MOBA, bản Liên Minh Huyền Thoại."),
    ("chuot", "Razer", "Razer Diamondback Plasma", 490000, None, 10, "fps,rgb,budget", 12, 200,
     {"Thiết kế": "Đối xứng", "Nút": "7", "LED": "Plasma đổi màu", "Kết nối": "Có dây"},
     "Mẫu chuột đối xứng kinh điển, đèn LED plasma."),
    ("chuot", "SteelSeries", "SteelSeries Rival 300 Fade Edition", 890000, None, 15, "fps,rgb", 12, 250,
     {"Cảm biến": "Optical", "DPI tối đa": "6.500", "Nút lập trình": "6", "LED": "RGB", "Phiên bản": "Fade"},
     "Rival 300 phối màu Fade, cảm biến quang học chính xác."),
    ("chuot", "Roccat", "Roccat Kone Pure", 990000, None, 12, "fps,moba,rgb", 24, 220,
     {"Cảm biến": "Laser", "DPI tối đa": "8.200", "Nút": "7", "Trọng lượng": "90 g"},
     "Bản thu gọn của Roccat Kone cho tay vừa và nhỏ."),
    ("chuot", "Roccat", "Roccat Kova", 890000, 790000, 16, "moba,rgb", 24, 240,
     {"Cảm biến": "Pro-Optic R6", "DPI tối đa": "7.000", "Thiết kế": "Thuận 2 tay", "Nút lập trình": "12 (Easy-Shift[+])"},
     "Chuột đối xứng cho cả người thuận tay trái."),
    # ---- Bàn phím
    ("ban-phim", "Razer", "Razer BlackWidow Ultimate", 1990000, 1690000, 18, "moba,mmo", 24, 1500,
     {"Layout": "Full-size", "Switch": "Cơ học clicky", "Phím macro": "5", "LED": "Xanh lá từng phím", "Cổng phụ": "USB + audio"},
     "Bàn phím cơ clicky, LED xanh từng phím, 5 phím macro riêng."),
    ("ban-phim", "Razer", "Razer BlackWidow Chroma", 2490000, 2090000, 14, "moba,rgb", 24, 1500,
     {"Layout": "Full-size", "Switch": "Razer Green", "LED": "Chroma RGB", "Phím macro": "5", "Cổng phụ": "USB + audio"},
     "BlackWidow với LED Chroma 16,8 triệu màu."),
    ("ban-phim", "Razer", "Razer DeathStalker", 1190000, None, 20, "moba,office", 12, 1200,
     {"Kiểu phím": "Màng, phím chiclet", "Layout": "Full-size", "LED": "Xanh lá", "Chống ghosting": "Có"},
     "Phím chiclet êm, mỏng, có đèn nền."),
    ("ban-phim", "Razer", "Razer Ornata Chroma", 1690000, 1390000, 22, "moba,rgb", 24, 1200,
     {"Switch": "Razer Mecha-Membrane", "Layout": "Full-size", "LED": "Chroma RGB", "Kê tay": "Đệm da rời"},
     "Lai giữa phím cơ và phím màng: gõ êm mà vẫn có độ nảy."),
    ("ban-phim", "Corsair", "Corsair K65", 1990000, None, 10, "fps,esports", 24, 900,
     {"Layout": "TKL", "Switch": "Cherry MX Red", "Khung": "Nhôm"},
     "TKL khung nhôm, Cherry MX Red cho FPS."),
    ("ban-phim", "Logitech G", "Logitech G910 Orion Spark", 2990000, 2490000, 9, "moba,rgb", 24, 1500,
     {"Switch": "Romer-G", "Phím G": "9", "LED": "RGB từng phím", "Đế điện thoại": "Arx Dock"},
     "Switch Romer-G nhanh, 9 phím G lập trình."),
    ("ban-phim", "Logitech G", "Logitech G710+", 2290000, 1890000, 12, "moba,office", 24, 1500,
     {"Switch": "Cherry MX Brown", "Phím G": "6", "LED": "Trắng, chỉnh 2 vùng", "Giảm ồn": "O-ring"},
     "Cherry MX Brown có đệm O-ring, gõ êm cả ngày."),
    ("ban-phim", "Keychron", "Keychron K8", 1690000, None, 25, "wireless,office", 12, 1100,
     {"Layout": "TKL 87 phím", "Kết nối": "Bluetooth / USB-C", "Switch": "Gateron", "Đèn nền": "Không", "Hệ điều hành": "macOS / Windows"},
     "TKL không dây, chuyển nhanh giữa 3 thiết bị."),
    ("ban-phim", "Keychron", "Keychron K4", 1890000, 1690000, 16, "wireless,office", 12, 1200,
     {"Layout": "96% (100 phím)", "Kết nối": "Bluetooth / USB-C", "Switch": "Gateron", "Hệ điều hành": "macOS / Windows"},
     "Đủ phím số trong thân máy gọn hơn full-size."),
    ("ban-phim", "Das Keyboard", "Das Keyboard Model S Ultimate", 3490000, None, 5, "office,premium", 24, 1600,
     {"Layout": "Full-size ISO", "Switch": "Cherry MX", "Keycap": "Trơn, không in ký tự", "Cổng phụ": "Hub USB 2 cổng"},
     "Keycap trơn không ký tự cho người gõ phím mù."),
    ("ban-phim", "SteelSeries", "SteelSeries Apex 5", 2290000, 1990000, 19, "moba,rgb", 12, 1400,
     {"Switch": "Hybrid Blue (cơ + màng)", "Màn hình": "OLED", "LED": "RGB từng phím", "Khung": "Nhôm", "Kê tay": "Nam châm"},
     "Switch hybrid có tiếng click, màn OLED hiển thị thông tin."),
    ("ban-phim", "Logitech G", "Logitech G PRO TKL", 2790000, 2290000, 15, "fps,esports,rgb", 24, 1000,
     {"Layout": "TKL", "Switch": "GX Blue Clicky", "Cáp": "Rời", "LED": "LIGHTSYNC RGB"},
     "Bàn phím TKL thiết kế cùng tuyển thủ, cáp rời dễ mang đi giải."),
    # ---- Tai nghe
    ("tai-nghe", "Logitech G", "Logitech G35 7.1", 1490000, None, 8, "moba", 24, 600,
     {"Âm thanh": "Dolby 7.1", "Driver": "40 mm", "Kết nối": "USB", "Phím G": "3"},
     "Âm thanh vòm 7.1, mic gập gọn vào thân."),
    ("tai-nghe", "Corsair", "Corsair Void Pro", 1690000, 1390000, 20, "fps,rgb", 24, 600,
     {"Driver": "50 mm", "Âm thanh": "7.1 giả lập", "Mic": "Khử ồn, gập để tắt"},
     "Đệm tai thoáng khí, đeo lâu không bí."),
    ("tai-nghe", "Razer", "Razer ManO'War 7.1", 1990000, 1690000, 11, "moba,rgb", 24, 700,
     {"Âm thanh": "7.1 giả lập", "Driver": "50 mm", "Mic": "Thu gọn vào thân", "LED": "Chroma RGB"},
     "Tai nghe vòm 7.1, mic rút gọn vào chụp tai."),
    ("tai-nghe", "Logitech G", "Logitech G733 Lightspeed", 2990000, 2490000, 23, "wireless,rgb,streaming,lightweight", 24, 500,
     {"Kết nối": "LIGHTSPEED 2.4GHz", "Driver": "PRO-G 40 mm", "Trọng lượng": "278 g", "Pin": "29 giờ", "Mic": "Blue VO!CE"},
     "Tai nghe không dây nhẹ, mic lọc giọng Blue VO!CE."),
    ("tai-nghe", "SteelSeries", "SteelSeries 3H", 690000, None, 30, "fps,budget", 12, 400,
     {"Kết nối": "3.5 mm", "Mic": "Gập được", "Thiết kế": "Gọn nhẹ"},
     "Tai nghe gọn nhẹ, mic gập, cắm 3.5 mm."),
    ("tai-nghe", "Creative", "Creative Sound BlasterX H5", 1490000, None, 13, "fps,esports", 12, 600,
     {"Driver": "50 mm FullSpectrum", "Kết nối": "3.5 mm", "Mic": "Rời được"},
     "Tai nghe analog chất âm trung thực, dùng được mọi thiết bị."),
    ("tai-nghe", "Microsoft", "Xbox One Chat Headset", 390000, None, 40, "budget", 12, 200,
     {"Kiểu": "Một bên tai (mono)", "Kết nối": "Cổng tai nghe tay cầm Xbox One đời đầu", "Mã": "Model 1564"},
     "Tai nghe chat chính hãng Xbox One, cắm thẳng vào tay cầm."),
    ("tai-nghe", "Logitech G", "Logitech G230", 890000, 729000, 35, "fps,budget", 24, 400,
     {"Driver": "40 mm", "Kết nối": "2 × 3.5 mm", "Mic": "Khử ồn, gập để tắt", "Đệm tai": "Vải thoáng khí"},
     "Tai nghe stereo nhẹ, đệm vải mát."),
    ("tai-nghe", "Razer", "Razer Megalodon 7.1", 1290000, None, 7, "moba", 24, 600,
     {"Âm thanh": "7.1 giả lập", "Kết nối": "USB", "Điều khiển": "Trên chụp tai"},
     "Âm thanh vòm 7.1 xử lý trên tai nghe, cắm USB là dùng."),
    ("tai-nghe", "SteelSeries", "SteelSeries Siberia v2 MSI Edition", 1190000, None, 9, "fps", 12, 500,
     {"Driver": "50 mm", "Mic": "Thu gọn vào thân", "Phiên bản": "MSI"},
     "Siberia v2 phối màu MSI, mic rút gọn."),
    # ---- Màn hình
    ("man-hinh", "MSI", "MSI Optix MPG341CQR", 13990000, 12490000, 4, "high-refresh,premium,streaming", 36, 11000,
     {"Kích thước": "34\" cong 1800R", "Tấm nền": "VA", "Độ phân giải": "3440 × 1440", "Tần số quét": "144 Hz", "Phản hồi": "1 ms (MPRT)"},
     "Ultrawide 21:9 144Hz, có webcam ẩn và đèn Mystic Light."),
    ("man-hinh", "Dell", "Dell S3423DWC", 10990000, 9490000, 5, "office,streaming", 36, 9500,
     {"Kích thước": "34\" cong 1800R", "Tấm nền": "VA", "Độ phân giải": "3440 × 1440", "Tần số quét": "100 Hz", "Cổng": "USB-C 65 W"},
     "Màn cong ultrawide cho làm việc và chơi game, sạc laptop qua USB-C."),
    ("man-hinh", "AORUS", "Gigabyte AORUS AD27QD", 9490000, None, 7, "high-refresh,fps,esports", 36, 8000,
     {"Kích thước": "27\"", "Tấm nền": "IPS", "Độ phân giải": "2560 × 1440", "Tần số quét": "144 Hz", "Phản hồi": "1 ms (MPRT)"},
     "Màn IPS 2K 144Hz, có tính năng Aim Stabilizer cho FPS."),
    ("man-hinh", "BenQ", "BenQ XL2420T", 2990000, None, 10, "high-refresh,fps,esports,budget", 24, 6500,
     {"Kích thước": "24\"", "Tấm nền": "TN", "Độ phân giải": "1920 × 1080", "Tần số quét": "120 Hz", "Phản hồi": "2 ms (GtG)"},
     "Màn esports 120Hz, chân đế chỉnh độ cao linh hoạt."),
    # ---- Ghế gaming
    ("ghe-gaming", "AORUS", "Ghế gaming AORUS", 6990000, 6290000, 8, "chair,premium", 24, 24000,
     {"Kiểu": "Ghế đua lưng cao", "Chất liệu": "Da PU", "Phụ kiện": "Gối đầu + gối lưng"},
     "Ghế gaming lưng cao của AORUS, đi kèm gối đầu và gối lưng."),
    ("ghe-gaming", "Thermaltake", "Thermaltake Argent E700 Storm Black", 26990000, 24990000, 2, "chair,premium", 36, 30000,
     {"Mã": "GGC-ARG-BBLFDL-01", "Chất liệu": "Da thật", "Thiết kế": "Studio F. A. Porsche", "Màu": "Đen Storm Black"},
     "Ghế da thật cao cấp, thiết kế bởi Studio F. A. Porsche."),
    # ---- Lót chuột
    ("lot-chuot", "Razer", "Razer Destructor 2", 590000, None, 25, "fps,speed", 12, 500,
     {"Bề mặt": "Cứng", "Đế": "Cao su chống trượt", "Phong cách": "Speed"},
     "Pad cứng lướt nhanh, đế cao su bám bàn."),
    ("lot-chuot", "SteelSeries", "SteelSeries 5L", 490000, None, 20, "fps,budget", 12, 400,
     {"Bề mặt": "Cứng", "Phong cách": "Speed"},
     "Pad cứng bền bỉ cho lối chơi tốc độ."),
    # ---- Tay cầm & vô lăng
    ("tay-cam", "Microsoft", "Xbox Elite Wireless Controller Series 2", 4290000, 3790000, 12, "wireless,premium,esports", 12, 700,
     {"Kết nối": "Xbox Wireless / Bluetooth / USB-C", "Pin": "Sạc, tới 40 giờ", "Cấu hình": "3 profile", "Cần analog": "Chỉnh lực căng"},
     "Tay cầm cao cấp: nút sau, cần analog chỉnh lực, pin 40 giờ."),
    ("tay-cam", "Microsoft", "Xbox Wireless Controller Carbon Black", 1390000, 1190000, 40, "wireless", 12, 400,
     {"Kết nối": "Xbox Wireless / Bluetooth / USB-C", "Pin": "2 × AA", "Nút Share": "Có", "Tương thích": "Xbox Series, Xbox One, PC"},
     "Tay cầm Xbox thế hệ mới, màu đen Carbon Black."),
    ("tay-cam", "Microsoft", "Xbox Wireless Controller Starfield Limited Edition", 1890000, None, 6, "wireless,premium", 12, 400,
     {"Kết nối": "Xbox Wireless / Bluetooth / USB-C", "Phiên bản": "Starfield (giới hạn)", "Tương thích": "Xbox Series, Xbox One, PC"},
     "Bản giới hạn lấy cảm hứng từ Starfield."),
    ("tay-cam", "Microsoft", "Xbox One Wireless Controller", 690000, None, 25, "wireless,budget", 12, 400,
     {"Kết nối": "Xbox Wireless / micro-USB", "Pin": "2 × AA", "Tương thích": "Xbox One, PC"},
     "Tay cầm Xbox One đời đầu, chơi PC qua cáp micro-USB."),
    ("tay-cam", "Microsoft", "Xbox Adaptive Controller", 2490000, None, 5, "wireless", 12, 1000,
     {"Cổng mở rộng": "19 jack 3.5 mm + 2 USB", "Nút lớn": "2", "Pin": "Sạc", "Tương thích": "Xbox, PC"},
     "Tay cầm cho game thủ khuyết tật, gắn thêm nút và cần ngoài."),
    ("tay-cam", "Sony", "DualSense White", 1690000, 1490000, 45, "wireless", 12, 400,
     {"Rung": "Haptic feedback", "Cò": "Adaptive trigger", "Kết nối": "Bluetooth / USB-C", "Mic": "Tích hợp"},
     "Tay cầm PS5 màu trắng nguyên bản, rung haptic chân thật."),
    ("tay-cam", "Sony", "DualSense Midnight Black", 1790000, 1590000, 30, "wireless", 12, 400,
     {"Rung": "Haptic feedback", "Cò": "Adaptive trigger", "Kết nối": "Bluetooth / USB-C", "Màu": "Midnight Black"},
     "DualSense màu đen Midnight Black."),
    ("tay-cam", "Sony", "DualSense Cobalt Blue", 1790000, None, 18, "wireless", 12, 400,
     {"Rung": "Haptic feedback", "Cò": "Adaptive trigger", "Kết nối": "Bluetooth / USB-C", "Màu": "Cobalt Blue"},
     "DualSense màu xanh Cobalt Blue."),
    ("tay-cam", "Sony", "DualSense Edge", 5290000, 4790000, 8, "wireless,premium,esports", 12, 700,
     {"Nút sau": "2, thay được", "Cần analog": "Module thay thế", "Cấu hình": "Lưu nhiều profile", "Kết nối": "Bluetooth / USB-C"},
     "Tay cầm PS5 chuyên nghiệp, thay được module cần analog."),
    ("tay-cam", "Sony", "DualShock 4", 1090000, 890000, 35, "wireless,budget", 12, 400,
     {"Kết nối": "Bluetooth / micro-USB", "Touchpad": "Có", "Light bar": "Có", "Tương thích": "PS4, PC"},
     "Tay cầm PS4 quen thuộc, chơi PC tốt qua Steam."),
    ("tay-cam", "Nintendo", "Nintendo Switch Pro Controller", 1690000, None, 22, "wireless", 12, 400,
     {"Rung": "HD Rumble", "NFC": "amiibo", "Pin": "Khoảng 40 giờ", "Sạc": "USB-C"},
     "Tay cầm chính hãng cho Switch, pin khoảng 40 giờ."),
    ("tay-cam", "8BitDo", "8BitDo Ultimate C Bluetooth", 590000, None, 40, "wireless,budget", 12, 300,
     {"Tương thích": "Nintendo Switch", "Kết nối": "Bluetooth", "Tính năng": "Rung, con quay hồi chuyển"},
     "Tay cầm Bluetooth giá mềm cho Nintendo Switch."),
    ("tay-cam", "8BitDo", "8BitDo Pro 2", 1090000, 990000, 26, "wireless", 12, 350,
     {"Tương thích": "Switch / PC / Android / macOS", "Kết nối": "Bluetooth / USB-C", "Nút sau": "2", "Pin": "1000 mAh"},
     "Tay cầm đa nền tảng, phần mềm chỉnh nút đầy đủ."),
    ("tay-cam", "Logitech G", "Logitech G923 PlayStation", 8990000, 7490000, 7, "racing,premium", 24, 9000,
     {"Phản hồi lực": "TRUEFORCE", "Góc xoay": "900°", "Bàn đạp": "3 pedal", "Tương thích": "PS5 / PS4 / PC"},
     "Vô lăng TRUEFORCE cảm nhận mặt đường chân thực."),
    ("tay-cam", "Logitech G", "Logitech G920 Driving Force", 6490000, 5490000, 9, "racing", 24, 9000,
     {"Phản hồi lực": "Mô-tơ kép", "Góc xoay": "900°", "Bàn đạp": "3 pedal", "Tương thích": "Xbox / PC"},
     "Vô lăng force feedback cho Xbox và PC."),
    ("tay-cam", "Logitech G", "Logitech G29 Driving Force", 6490000, 5290000, 10, "racing", 24, 9000,
     {"Phản hồi lực": "Mô-tơ kép", "Góc xoay": "900°", "Bàn đạp": "3 pedal", "Tương thích": "PlayStation / PC"},
     "Vô lăng bọc da khâu tay cho PlayStation và PC."),
    ("tay-cam", "Logitech G", "Logitech F310", 390000, None, 70, "budget", 24, 300,
     {"Kết nối": "Có dây USB", "Chế độ": "XInput / DirectInput", "Tương thích": "PC"},
     "Tay cầm có dây giá rẻ, cắm là chơi trên PC."),
    ("tay-cam", "Logitech G", "Logitech F710", 790000, 690000, 30, "wireless,budget", 24, 350,
     {"Kết nối": "Không dây 2.4GHz", "Rung": "Mô-tơ kép", "Chế độ": "XInput / DirectInput", "Pin": "2 × AA"},
     "Tay cầm không dây 2.4GHz cho PC, có rung."),
    ("tay-cam", "Thrustmaster", "Thrustmaster TX Racing Wheel Leather Edition", 12990000, None, 3, "racing,premium", 24, 12000,
     {"Góc xoay": "900°", "Mô-tơ": "Không chổi than", "Vô lăng": "Bọc da thật", "Tương thích": "Xbox / PC"},
     "Vô lăng bọc da thật, mô-tơ không chổi than mượt và êm."),
    ("tay-cam", "Thrustmaster", "Thrustmaster Ferrari GT Experience", 2190000, None, 12, "racing,budget", 12, 4000,
     {"Góc xoay": "240°", "Bàn đạp": "2 pedal", "Tương thích": "PS3 / PC"},
     "Bộ vô lăng nhập môn mang phong cách Ferrari."),
    ("tay-cam", "Thrustmaster", "Thrustmaster T.16000M", 1890000, None, 10, "flight", 24, 1000,
     {"Cảm biến": "Hall effect H.E.A.R.T", "Độ phân giải": "16-bit", "Nút": "16", "Thiết kế": "Thuận 2 tay"},
     "Cần lái mô phỏng bay cảm biến từ, độ chính xác cao."),
    ("tay-cam", "Thrustmaster", "Thrustmaster TCA Sidestick Airbus Edition", 1690000, None, 8, "flight", 24, 1000,
     {"Cảm biến": "Hall effect H.E.A.R.T", "Thiết kế": "Mô phỏng sidestick Airbus, thuận 2 tay"},
     "Cần lái mô phỏng buồng lái Airbus cho Flight Simulator."),
    ("tay-cam", "Turtle Beach", "Turtle Beach Stealth Ultra", 5490000, 4990000, 6, "wireless,premium", 12, 700,
     {"Tương thích": "Xbox / PC", "Kết nối": "2.4GHz / Bluetooth", "Màn hình": "Hiển thị thông báo trên tay cầm", "Sạc": "Đế sạc kèm theo"},
     "Tay cầm Xbox có màn hình hiển thị và đế sạc."),
    ("tay-cam", "Valve", "Steam Controller", 2490000, None, 10, "wireless", 12, 500,
     {"Thế hệ": "Thứ 2", "Phụ kiện kèm": "Puck", "Tương thích": "Steam (PC, Steam Deck)"},
     "Tay cầm thế hệ mới của Valve, kèm Puck."),
    # ---- Micro & Stream
    ("micro-stream", "Blue Microphones", "Blue Yeti Blackout", 3290000, 2790000, 15, "streaming", 24, 1600,
     {"Kiểu thu": "4 chế độ (cardioid, stereo, omni, figure-8)", "Kết nối": "USB", "Chất lượng": "16-bit / 48 kHz"},
     "Micro USB bán chạy nhất cho streamer, màu đen Blackout."),
    ("micro-stream", "Blue Microphones", "Blue Yeti", 2990000, 2590000, 18, "streaming", 24, 1600,
     {"Kiểu thu": "4 chế độ (cardioid, stereo, omni, figure-8)", "Kết nối": "USB", "Chất lượng": "16-bit / 48 kHz"},
     "Micro USB 3 capsule, chỉnh kiểu thu bằng một núm xoay."),
    ("micro-stream", "Blue Microphones", "Blue Snowball", 1290000, 1090000, 25, "streaming,budget", 12, 800,
     {"Kiểu thu": "Cardioid / omni", "Kết nối": "USB", "Thiết kế": "Tròn cổ điển"},
     "Micro USB nhập môn cho voice chat và học online."),
    ("micro-stream", "Shure", "Shure MV7", 6490000, 5790000, 7, "streaming,premium", 24, 1000,
     {"Kiểu thu": "Động (dynamic)", "Kết nối": "USB + XLR", "Tính năng": "Auto Level Mode"},
     "Micro động chuẩn podcast, cắm được cả USB lẫn XLR."),
    ("micro-stream", "Rode", "Rode NT-USB", 4290000, None, 9, "streaming", 12, 900,
     {"Kiểu thu": "Condenser cardioid", "Kết nối": "USB", "Monitor": "Jack 3.5 mm không độ trễ", "Phụ kiện": "Màng lọc pop"},
     "Micro condenser USB chất âm phòng thu."),
    ("micro-stream", "Rode", "Rode NT-USB Mini", 2690000, 2390000, 14, "streaming", 12, 600,
     {"Kiểu thu": "Condenser cardioid", "Kết nối": "USB", "Chất lượng": "24-bit / 48 kHz", "Chân đế": "Nam châm, tháo nhanh"},
     "Micro USB nhỏ gọn, chân đế nam châm."),
    ("micro-stream", "Audio-Technica", "Audio-Technica AT2020", 2590000, None, 12, "streaming", 12, 700,
     {"Kiểu thu": "Condenser cardioid", "Kết nối": "XLR (cần phantom 48V)", "Tần số": "20 – 20.000 Hz"},
     "Micro condenser XLR kinh điển cho phòng thu tại nhà."),
    ("micro-stream", "Elgato", "Elgato Stream Deck +", 5490000, None, 6, "streaming", 24, 800,
     {"Phím LCD": "8", "Núm xoay": "4", "Màn cảm ứng": "Có"},
     "Bảng điều khiển stream với núm xoay chỉnh âm lượng, đèn."),
    ("micro-stream", "Elgato", "Elgato Cam Link", 2990000, None, 10, "streaming", 24, 200,
     {"Đầu vào": "HDMI", "Đầu ra": "USB 3.0", "Cài đặt": "Không cần driver"},
     "Biến máy ảnh, máy quay thành webcam qua HDMI."),
    ("micro-stream", "Elgato", "Elgato Game Capture HD60 S", 3990000, 3490000, 8, "streaming", 24, 400,
     {"Ghi hình": "1080p60", "Kết nối": "USB 3.0 (USB-C)", "Passthrough": "HDMI độ trễ thấp"},
     "Card capture rời để stream game console lên PC."),
    ("micro-stream", "Elgato", "Elgato Wave:3", 3990000, 3490000, 9, "streaming", 24, 900,
     {"Kiểu thu": "Condenser cardioid", "Kết nối": "USB-C", "Chống vỡ tiếng": "Clipguard", "Phần mềm": "Wave Link"},
     "Micro USB có Clipguard chống vỡ tiếng khi hét."),
    ("micro-stream", "Logitech G", "Logitech C920 HD Pro", 1690000, 1390000, 30, "streaming,office", 24, 300,
     {"Độ phân giải": "1080p 30fps", "Mic": "Stereo kép", "Lấy nét": "Tự động"},
     "Webcam Full HD phổ biến nhất cho stream và họp online."),
    ("micro-stream", "Logitech G", "Logitech Brio 301", 1290000, None, 28, "office,streaming", 24, 300,
     {"Độ phân giải": "1080p 30fps", "Che ống kính": "Có", "Kết nối": "USB-C", "Mic": "Khử ồn"},
     "Webcam Full HD có nắp che riêng tư."),
    ("micro-stream", "Logitech G", "Logitech StreamCam", 3490000, 2990000, 11, "streaming", 24, 400,
     {"Độ phân giải": "1080p 60fps", "Kết nối": "USB-C", "Quay dọc": "9:16"},
     "Webcam 60fps quay được dọc cho TikTok, Shorts."),
    ("micro-stream", "Focusrite", "Focusrite Scarlett Solo 3rd Gen", 2990000, None, 10, "streaming", 24, 600,
     {"Ngõ vào": "1 XLR + 1 instrument", "Chất lượng": "24-bit / 192 kHz", "Phantom": "48V", "Chế độ": "Air"},
     "Sound card thu âm để dùng micro XLR như AT2020."),
    ("micro-stream", "AVerMedia", "AVerMedia Live Gamer HD 2", 3290000, None, 7, "streaming", 24, 400,
     {"Kiểu": "Card gắn trong PCIe", "Ghi hình": "1080p60", "Passthrough": "HDMI"},
     "Card capture gắn trong PC, ghi 1080p60 không nén."),
]

# Demo products sold in earlier versions of this seed, by category. They have no exact photo, so `--sync`
# removes them; their past order lines keep name / SKU and get the category stamped from here, so
# revenue-by-category reports stay complete.
RETIRED_BY_CATEGORY = {
    "chuot": [
        "Corsair Harpoon RGB Wireless", "DareU EM901X Wireless", "E-Dra EM624", "Logitech G304 Lightspeed",
        "Logitech G502 X Plus", "Razer DeathAdder V3", "Razer Mamba", "Razer Naga 2014", "Razer Naga V2 HyperSpeed",
        "Razer Viper V3 Pro", "SteelSeries Rival 3", "Zowie EC2-CW",
    ],
    "ban-phim": [
        "Akko 5075B Plus", "Corsair K70 RGB Pro", "DareU EK87 V2", "E-Dra EK387 Pro", "HyperX Alloy Origins Core",
        "Keychron K8 Pro", "Keychron Q1 Pro", "Logitech G Pro X TKL Lightspeed", "Logitech G915 TKL Lightspeed",
        "Razer BlackWidow Ultimate 2014", "Razer BlackWidow V4", "Razer Huntsman Mini", "SteelSeries Apex Pro TKL",
    ],
    "tai-nghe": [
        "Corsair HS65 Surround", "Corsair HS80 RGB Wireless", "HyperX Cloud III", "HyperX Cloud Stinger 2",
        "Logitech G Astro A50 X", "Logitech G Pro X 2 Lightspeed", "Logitech G435 Lightspeed", "Razer BlackShark V2 X",
        "Razer Kraken V3 X", "Sony INZONE H5", "SteelSeries Arctis Nova 1", "SteelSeries Arctis Nova 7",
    ],
    "man-hinh": [
        'AOC 24G2SP 24" 165Hz', 'ASUS ROG Strix XG27ACS 27" 2K 180Hz', "ASUS ROG Strix XG32VQR",
        'ASUS TUF Gaming VG249Q3A 24" 180Hz', 'BenQ Zowie XL2546K 24.5" 240Hz', 'Dell Alienware AW2725DF 27" QD-OLED 360Hz',
        'LG UltraGear 24GN60R 24" 144Hz', 'LG UltraGear 27GR75Q 27" 2K 165Hz', 'MSI G274QPF E2 27" 2K 180Hz',
        'Samsung Odyssey G5 32" cong 165Hz', 'Samsung Odyssey G7 27" 2K 240Hz', 'ViewSonic VX2479-HD-PRO 24" 180Hz',
        'ViewSonic XG2431 24" 240Hz',
    ],
    "ghe-gaming": [
        "Ghế Anda Seat Kaiser 3", "Ghế Anda Seat Phantom 3", "Ghế Corsair TC100 Relaxed", "Ghế Corsair TC200 Leatherette",
        "Ghế Cougar Armor One", "Ghế DXRacer Formula", "Ghế E-Dra Hunter EGC206", "Ghế E-Dra Mars EGC224", "Ghế Razer Iskur V2",
        "Ghế Secretlab Titan Evo", "Ghế Warrior Crusader WGC306", "Ghế Warrior Raider WGC206",
    ],
    "lot-chuot": [
        "Akko Pad Neon RGB", "Corsair MM300 Pro Extended", "HyperX Pulsefire Mat XL", "Logitech G640", "Logitech G840 XL",
        "Lót chuột E-Dra EMP02 Deskmat", "Razer Gigantus V2 XXL", "Razer Strider XXL", "SteelSeries QcK Heavy XXL",
        "SteelSeries QcK Prism XL", "Zowie G-SR II", "Zowie G-SR-SE Rouge",
    ],
    "tay-cam": [
        "8BitDo Ultimate Bluetooth", "Tay cầm DualSense PS5", "Tay cầm DualShock 4", "Tay cầm Nintendo Switch Pro Controller",
        "Tay cầm Razer Wolverine V2", "Tay cầm Sony DualSense Edge", "Tay cầm Xbox Elite Series 2",
        "Tay cầm Xbox Wireless Controller", "Vô lăng Logitech G29 Driving Force", "Vô lăng Logitech G923 TrueForce",
        "Vô lăng Thrustmaster T248",
    ],
    "micro-stream": [
        "Elgato Cam Link 4K", "Elgato HD60 X Capture Card", "Elgato Stream Deck MK.2", "Micro Elgato Wave:3",
        "Micro Fifine AmpliGame A6V", "Micro HyperX QuadCast S", "Micro Logitech G Yeti GX", "Micro Razer Seiren Mini",
        "Micro Rode PodMic USB", "Micro Shure MV7+", "Webcam Logitech C922 Pro Stream", "Webcam Razer Kiyo Pro",
        "Đèn Elgato Key Light Air",
    ],
}
RETIRED = [name for names in RETIRED_BY_CATEGORY.values() for name in names]


COMPLEMENTS = {
    "chuot": ["lot-chuot", "ban-phim", "tai-nghe"],
    "ban-phim": ["chuot", "lot-chuot"],
    "tai-nghe": ["micro-stream", "chuot"],
    "man-hinh": ["ghe-gaming", "ban-phim"],
    "ghe-gaming": ["man-hinh", "lot-chuot"],
    "lot-chuot": ["chuot"],
    "tay-cam": ["tai-nghe", "man-hinh"],
    "micro-stream": ["tai-nghe", "micro-stream"],
}

LAST = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý"]
MIDDLE = ["Văn", "Thị", "Minh", "Quốc", "Gia", "Ngọc", "Đức", "Thanh", "Hoàng", "Anh", "Bảo", "Tuấn"]
FIRST = ["An", "Bình", "Châu", "Dũng", "Đạt", "Giang", "Hải", "Hiếu", "Hùng", "Khang", "Khoa", "Linh", "Long", "Minh", "Nam", "Nhân", "Phúc", "Quân", "Sơn", "Tâm", "Thảo", "Thịnh", "Trí", "Trung", "Tú", "Vy", "Yến", "Huy", "Kiệt", "Lộc"]
# Wards after the 2025 reform (province -> ward/commune, no district level)
WARDS = {"TP. Hồ Chí Minh": ["Phường Sài Gòn", "Phường Bến Thành", "Phường Diên Hồng", "Phường Bình Thạnh", "Phường Gò Vấp", "Phường Thủ Đức", "Phường Tân Bình", "Phường Phú Nhuận", "Phường Thủ Dầu Một", "Phường Vũng Tàu"],
         "Hà Nội": ["Phường Cầu Giấy", "Phường Đống Đa", "Phường Hai Bà Trưng", "Phường Thanh Xuân", "Phường Hoàng Mai"], "Đà Nẵng": ["Phường Hải Châu", "Phường Thanh Khê", "Phường Sơn Trà"]}
_TOP_PROVINCES = [("TP. Hồ Chí Minh", 51), ("Hà Nội", 20), ("Đà Nẵng", 6), ("Đồng Nai", 4), ("Cần Thơ", 4), ("Hải Phòng", 3), ("Khánh Hòa", 2)]
PROVINCE_WEIGHTS = _TOP_PROVINCES + [(p, 1) for p in PROVINCES if p not in dict(_TOP_PROVINCES)]
REVIEW_TEXT = {
    5: ["Hàng chính hãng, đóng gói kỹ, giao nhanh. Rất đáng tiền!", "Dùng cực sướng, leo rank mượt hẳn. Shop tư vấn nhiệt tình.", "Chất lượng hoàn thiện tốt, cảm giác cao cấp. 10 điểm.", "Giao 2H thật, chiều đặt tối đã chơi. Quá ổn."],
    4: ["Sản phẩm tốt, chỉ có hộp hơi móp nhẹ.", "Ổn trong tầm giá, phần mềm hơi khó dùng lúc đầu.", "Dùng tốt, giao hơi chậm 1 ngày so với dự kiến."],
    3: ["Tạm được, chưa thấy khác biệt nhiều so với đồ cũ.", "Dùng ổn nhưng giá hơi cao."],
    2: ["Sản phẩm bị lỗi nhẹ, shop đã đổi mới nhanh chóng."],
}
SEARCHES = ["chuột không dây", "logitech", "bàn phím cơ", "tai nghe", "razer", "màn hình 144hz", "ghế gaming", "lót chuột", "chuot fps", "ban phim co", "dualsense", "micro stream", "tay cầm", "superlight", "vô lăng", "steelseries", "xbox"]
ZERO_SEARCHES = ["steam deck", "loa bluetooth", "ghế công thái học văn phòng", "laptop gaming", "card màn hình", "bàn gaming"]
CHAT_SAMPLES = [("Chuột FPS dưới 1 triệu", "recommend"), ("Phí ship bao nhiêu?", "shipping"), ("Có mã giảm giá không?", "promotion"), ("chính sách đổi trả", "returns"),
                ("tai nghe không dây", "recommend"), ("đơn hàng của tôi đâu", "order_status"), ("bảo hành bao lâu", "warranty"), ("trả góp được không", "payment"),
                ("shop có bán laptop không", "unknown"), ("xin chào", "greeting"), ("bàn phím cơ tầm 1tr5", "recommend"), ("có card màn hình không", "unknown")]


class Command(BaseCommand):
    help = "Seed the database with realistic demo data for LevelUp Gear"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing catalogue/orders first")
        parser.add_argument("--orders", type=int, default=700)
        parser.add_argument("--seed", type=int, default=2026)
        parser.add_argument("--sync", action="store_true",
                            help="Existing database: retire old demo products, add missing ones, refresh specs, photos and banners, drop empty brands")

    def handle(self, *args, **opts):
        self.rnd = random.Random(opts["seed"])
        if opts["reset"]:
            self._reset()
        self._secure_admin()
        if Product.objects.exists():
            self._restore_missing_images()
            for old, new in BANNER_SUBTITLE_FIXES.items():
                Banner.objects.filter(subtitle=old).update(subtitle=new)
            if opts["sync"]:
                self._sync()
                return
            self.stdout.write(self.style.WARNING("Products already exist — use --reset to rebuild. Skipping."))
            return
        with transaction.atomic():
            self._reference_data()
            products = self._catalogue()
            users = self._users()
            self._orders(products, users, opts["orders"])
            self._behaviour(products, users)
        engine.invalidate()
        self.stdout.write(self.style.SUCCESS(
            f"Done: {Product.objects.count()} products, {User.objects.count()} users, {Order.objects.count()} orders, "
            f"{Review.objects.count()} reviews, {SiteVisit.objects.count()} visits."
        ))
        if settings.DEBUG:
            self.stdout.write(f"Staff login:  admin / {DEMO_ADMIN_PASSWORD}   ·   Customer login: demo / {DEMO_CUSTOMER_PASSWORD}")
        else:
            self.stdout.write(f"Staff login:  admin / (DJANGO_SUPERUSER_PASSWORD)   ·   Customer login: demo / {DEMO_CUSTOMER_PASSWORD}")
        self.stdout.write(f"Django admin: /{settings.ADMIN_URL}")

    # ------------------------------------------------------------------
    def _admin_password(self):
        """Password for the seeded staff account, or None when none may be set.

        The README's demo password is only acceptable on a developer machine
        (DEBUG=True). Anywhere else it would hand the dashboard — and every
        customer's personal data — to whoever has read the README.
        """
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        if password:
            return password
        return DEMO_ADMIN_PASSWORD if settings.DEBUG else None

    def _secure_admin(self):
        """Runs on every start (also when the catalogue already exists).

        * Production + an "admin" still using the public demo password (e.g. a
          deployment seeded before this fix) → switch to DJANGO_SUPERUSER_PASSWORD,
          or lock the password if that variable is not set.
        * "admin" with a locked password and DJANGO_SUPERUSER_PASSWORD now set → apply it.
        """
        if settings.DEBUG:
            return
        admin = User.objects.filter(username="admin").first()
        if admin is None:
            return
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        if admin.check_password(DEMO_ADMIN_PASSWORD) or (password and not admin.has_usable_password()):
            if password:
                admin.set_password(password)
                self.stdout.write(self.style.SUCCESS("Staff account 'admin': password set from DJANGO_SUPERUSER_PASSWORD."))
            else:
                admin.set_unusable_password()
                self.stdout.write(self.style.WARNING(
                    "Staff account 'admin' was using the public demo password — login disabled. "
                    "Set DJANGO_SUPERUSER_PASSWORD and restart to enable it."
                ))
            admin.save(update_fields=["password"])

    # ------------------------------------------------------------------
    def _restore_missing_images(self):
        """Hosts with an ephemeral disk (Render free tier) lose /media on restart — put the product photos back.

        A lost file with no photo to restore it from (an admin upload, old generated art) is removed
        rather than left as a broken image.
        """
        restored = dropped = 0
        for img in ProductImage.objects.select_related("product"):
            if img.image and img.image.storage.exists(img.image.name):
                continue
            data = demo_photo(img.product.name) if img.sort_order == 0 else None
            if data:
                img.image.save(f"{img.product.slug}-photo.jpg", ContentFile(data), save=True)
                restored += 1
            else:
                img.delete()
                dropped += 1
        if restored or dropped:
            self.stdout.write(f"Product images: {restored} restored, {dropped} missing files removed.")

    def _reset(self):
        self.stdout.write("Resetting demo data…")
        for M in (ChatMessage, SearchLog, ProductView, SiteVisit, Payment, OrderStatusHistory, OrderItem, Order, Review, ProductImage, Product, Brand, Category, Coupon, DeliveryMethod, Banner, FAQ):
            M.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()

    def _reference_data(self):
        for i, (slug, name, icon, desc) in enumerate(CATEGORIES):
            Category.objects.update_or_create(slug=slug, defaults={"name": name, "icon": icon, "description": desc, "sort_order": i})
        for b in sorted({row[1] for row in P}):  # only brands that have products
            Brand.objects.get_or_create(name=b, defaults={"country": BRANDS[b]})
        DeliveryMethod.objects.get_or_create(code="standard", defaults=dict(name="Giao tiêu chuẩn", description="GHN / GHTK", base_fee=30000, fee_per_extra_kg=5000, outer_region_surcharge=10000, min_days=2, max_days=4, sort_order=0))
        DeliveryMethod.objects.get_or_create(code="express", defaults=dict(name="Giao nhanh 2H", description="Ahamove — nhận trong 2 giờ", base_fee=45000, fee_per_extra_kg=8000, outer_region_surcharge=0, min_days=0, max_days=0, only_provinces="TP. Hồ Chí Minh, Hà Nội", free_ship_eligible=False, sort_order=1))
        DeliveryMethod.objects.get_or_create(code="pickup", defaults=dict(name="Nhận tại cửa hàng", description="Showroom 268 Lý Thường Kiệt, P. Diên Hồng, TP.HCM", base_fee=0, min_days=0, max_days=0, only_provinces="TP. Hồ Chí Minh", is_pickup=True, sort_order=2))
        now = timezone.now()
        coupons = [
            ("WELCOME10", "Giảm 10% (tối đa 200K) cho đơn đầu tiên", Coupon.PERCENT, 10, 200000, 0, True),
            ("GAMER50K", "Giảm 50.000₫ cho đơn từ 800K", Coupon.FIXED, 50000, None, 800000, False),
            ("FREESHIP", "Miễn phí vận chuyển đơn từ 300K", Coupon.FREESHIP, 0, None, 300000, False),
            ("LEVELUP15", "Giảm 15% tối đa 500K — tuần lễ LevelUp", Coupon.PERCENT, 15, 500000, 2000000, False),
        ]
        for code, desc, kind, value, maxd, mino, first in coupons:
            Coupon.objects.get_or_create(code=code, defaults=dict(description=desc, kind=kind, value=value, max_discount=maxd, min_order=mino, first_order_only=first, valid_from=now - timedelta(days=200), valid_to=now + timedelta(days=120)))
        for i, b in enumerate(BANNERS):
            fields = {k: v for k, v in b.items() if k != "title"}
            Banner.objects.get_or_create(title=b["title"], defaults=dict(fields, kicker=BANNER_KICKERS[b["theme"]], sort_order=i))
        faqs = [
            ("Shop có bán hàng chính hãng không?", "chinh hang,fake,gia,that", "100% sản phẩm nhập từ nhà phân phối chính thức tại Việt Nam, có tem bảo hành và hoá đơn VAT."),
            ("Có hỗ trợ trả góp không?", "tra gop,gop,installment", "Hỗ trợ trả góp 0% qua thẻ tín dụng (VNPay) cho đơn từ 3 triệu, kỳ hạn 3–12 tháng."),
            ("Tôi có được kiểm tra hàng trước khi nhận không?", "kiem tra hang,dong kiem,xem hang", "Có. Với đơn COD bạn được mở hộp kiểm tra trước khi thanh toán."),
            ("Showroom mở cửa giờ nào?", "gio mo cua,showroom,mo cua", "Showroom mở cửa 9:00–21:00 tất cả các ngày, kể cả Chủ nhật."),
            ("Có xuất hoá đơn VAT không?", "hoa don,vat,xuat hoa don", "Có. Chọn 'Xuất hoá đơn VAT' ở bước thanh toán và nhập tên công ty, mã số thuế."),
        ]
        for q, k, a in faqs:
            FAQ.objects.get_or_create(question=q, defaults={"keywords": k, "answer": a})

    def _catalogue(self):
        cats = {c.slug: c for c in Category.objects.all()}
        brands = {b.name: b for b in Brand.objects.all()}
        now = timezone.now()
        products = []
        self.stdout.write(f"Loading {len(P)} product photos…")
        for i, row in enumerate(P):
            p = self._make_product(i, row, cats, brands, now)
            products.append(p)
        return products

    @staticmethod
    def _content(row):
        """The descriptive fields of a catalogue row — what `--sync` refreshes. Price and stock stay the shop's."""
        cat, brand, name, price, sale, stock, tags, warranty, weight, specs, short = row
        return dict(
            short_description=short, specs=specs, tags=tags, warranty_months=warranty, weight_grams=weight,
            description=(
                f"{name} là lựa chọn được nhiều game thủ tin dùng. {short}\n\n"
                f"Điểm nổi bật:\n• {' • '.join(f'{k}: {v}' for k, v in list(specs.items())[:3])}\n\n"
                f"Sản phẩm chính hãng {brand}, bảo hành {warranty} tháng tại LevelUp Gear. Giao nhanh 2H nội thành TP.HCM, đổi mới trong 7 ngày nếu lỗi."
            ),
        )

    def _make_product(self, i, row, cats, brands, now, sku=None):
        cat, brand, name, price, sale, stock = row[:6]
        p = Product(
            category=cats[cat], brand=brands[brand], name=name, sku=sku or f"LU-{cat[:3].upper()}-{i + 1:03d}",
            price=price, sale_price=sale, cost_price=int(price * self.rnd.uniform(0.68, 0.78) / 1000) * 1000,
            stock=stock, is_featured=i % 5 == 0, **self._content(row),
        )
        p.save()
        Product.objects.filter(pk=p.pk).update(created_at=now - timedelta(days=200 - i * 2))
        ProductImage.objects.create(product=p, alt=name, sort_order=0, image=ContentFile(demo_photo(name), name=f"{p.slug}-photo.jpg"))
        return p

    @staticmethod
    def _read(field):
        try:
            with field.open("rb") as f:
                return f.read()
        except (OSError, ValueError):
            return None

    def _sync(self):
        """Bring an already-seeded database up to the current demo catalogue without touching orders or customers.

        * products of older demo catalogues (RETIRED) are deleted — past orders keep their name/SKU snapshot;
        * missing catalogue products are added; the ones already there get the current specs and copy
          (price, stock and sales are left alone);
        * every catalogue product ends up with its photo as the only seed-owned image (older generated
          art is removed); images an admin uploaded are never touched;
        * brands left without products are deleted;
        * the home-page banners get the current copy.
        """
        with transaction.atomic():
            for old, new in BANNER_RENAMED.items():
                if not Banner.objects.filter(title=new).exists():
                    Banner.objects.filter(title=old).update(title=new)
            self._reference_data()
            for b in BANNERS:
                Banner.objects.filter(title=b["title"]).update(subtitle=b["subtitle"], kicker=BANNER_KICKERS[b["theme"]])
            cats = {c.slug: c for c in Category.objects.all()}
            brands = {b.name: b for b in Brand.objects.all()}
            current = {row[2] for row in P}
            # past order lines of retired products keep their category (revenue by category stays complete)
            for slug, names in RETIRED_BY_CATEGORY.items():
                if slug in cats:
                    OrderItem.objects.filter(product_name__in=names, category_name="").update(category_name=cats[slug].name)
            retired = 0
            for p in Product.objects.filter(name__in=set(RETIRED) - current).select_related("category"):
                p.order_items.filter(category_name="").update(category_name=p.category.name)
                for img in p.images.all():
                    img.image.delete(save=False)
                p.delete()
                retired += 1
            existing = set(Product.objects.values_list("name", flat=True))
            customers = list(User.objects.filter(is_staff=False).order_by("?")[:200])
            now = timezone.now()
            added = []
            for i, row in enumerate(P):
                if row[2] in existing:
                    continue
                p = self._make_product(i, row, cats, brands, now, sku=self._free_sku(row[0], i))
                added.append(p)
                # a few verified reviews + sales history so new products don't look abandoned next to the old ones
                for u in self.rnd.sample(customers, min(len(customers), self.rnd.randint(2, 9))):
                    rating = self.rnd.choices([5, 4, 3, 2], weights=[62, 27, 8, 3])[0]
                    r = Review.objects.create(product=p, user=u, rating=rating, comment=self.rnd.choice(REVIEW_TEXT[rating]), is_verified_purchase=True,
                                              title={5: "Tuyệt vời", 4: "Hài lòng", 3: "Tạm ổn", 2: "Chưa ưng"}[rating])
                    Review.objects.filter(pk=r.pk).update(created_at=now - timedelta(days=self.rnd.randint(1, 60)))
                Product.objects.filter(pk=p.pk).update(sold_count=self.rnd.randint(8, 140))
            rows = {row[2]: row for row in P}
            refreshed = 0
            for p in Product.objects.filter(name__in=existing & current).select_related("brand", "category"):
                row = rows[p.name]
                fields = dict(self._content(row), category=cats[row[0]], brand=brands[row[1]])
                if any(getattr(p, k) != v for k, v in fields.items()):
                    for k, v in fields.items():
                        setattr(p, k, v)
                    p.save()  # also rebuilds search_text
                    refreshed += 1
            swapped = removed = 0
            for p in Product.objects.filter(name__in=current).prefetch_related("images"):
                owned = [img for img in p.images.all() if seed_owned(img)]
                main = next((img for img in owned if img.sort_order == 0), None)
                for img in owned:
                    if img is not main:
                        img.image.delete(save=False)
                        img.delete()
                        removed += 1
                data = demo_photo(p.name)
                if main is None:
                    ProductImage.objects.create(product=p, alt=p.name, sort_order=0, image=ContentFile(data, name=f"{p.slug}-photo.jpg"))
                    swapped += 1
                elif data != self._read(main.image):
                    main.image.delete(save=False)
                    main.image.save(f"{p.slug}-photo.jpg", ContentFile(data), save=True)
                    swapped += 1
            empty_brands, _ = Brand.objects.filter(products__isnull=True).delete()
            for b in Banner.objects.filter(kicker=""):
                b.kicker = BANNER_KICKERS.get(b.theme, "")
                b.save(update_fields=["kicker"])
        engine.invalidate()
        per_cat = Counter(Product.objects.filter(is_active=True).values_list("category__slug", flat=True))
        self.stdout.write(self.style.SUCCESS(
            f"Sync: -{retired} retired, +{len(added)} products, {refreshed} updated, {swapped} photos applied, {removed} old images removed, "
            f"{empty_brands} empty brands removed. Per category: {dict(per_cat)}"
        ))

    @staticmethod
    def _free_sku(cat, i):
        """The catalogue SKU, or the next free number in the category when an older product holds it."""
        prefix = f"LU-{cat[:3].upper()}-"
        n = i + 1
        while Product.objects.filter(sku=f"{prefix}{n:03d}").exists():
            n += 1
        return f"{prefix}{n:03d}"

    def _users(self):
        if not User.objects.filter(username="admin").exists():
            password = self._admin_password()
            User.objects.create_superuser("admin", "admin@levelupgear.vn", password, first_name="Quản trị", last_name="LevelUp", data_consent_at=timezone.now())
            if password is None:  # create_superuser(password=None) → unusable password
                self.stdout.write(self.style.WARNING(
                    "DJANGO_SUPERUSER_PASSWORD is not set — staff account 'admin' created without a usable password. "
                    "Set the variable and restart to enable it."
                ))
        demo, created = User.objects.get_or_create(
            username="demo", defaults=dict(email="demo@levelupgear.vn", first_name="Đạt", last_name="Lư", phone="0901234567", gamer_tag="LevelUpDat", favorite_genre="fps", data_consent_at=timezone.now(), marketing_opt_in=True)
        )
        if created:
            demo.set_password(DEMO_CUSTOMER_PASSWORD)
            demo.save()
            Address.objects.create(user=demo, full_name="Lư Đạt", phone="0901234567", province="TP. Hồ Chí Minh", ward="Phường Diên Hồng", street="268 Lý Thường Kiệt", is_default=True)
        users = [demo]
        now = timezone.now()
        for i in range(140):
            first, last = self.rnd.choice(FIRST), self.rnd.choice(LAST)
            joined = now - timedelta(days=int(180 * (1 - self.rnd.random() ** 0.8)), hours=self.rnd.randint(0, 23))
            u = User(username=f"user{i + 1:03d}", email=f"user{i + 1:03d}@example.com", first_name=f"{self.rnd.choice(MIDDLE)} {first}", last_name=last,
                     phone=f"09{self.rnd.randint(10000000, 99999999)}", favorite_genre=self.rnd.choice(["fps", "moba", "rpg", "racing", "casual"]),
                     marketing_opt_in=self.rnd.random() < 0.4, data_consent_at=joined, date_joined=joined)
            u.set_unusable_password()
            users.append(u)
        User.objects.bulk_create(users[1:])
        return list(User.objects.filter(is_staff=False))

    def _pick_province(self):
        r = self.rnd.uniform(0, sum(w for _, w in PROVINCE_WEIGHTS))
        for p, w in PROVINCE_WEIGHTS:
            r -= w
            if r <= 0:
                return p
        return PROVINCES[0]

    def _orders(self, products, users, n_orders):
        by_cat = {}
        for p in products:
            by_cat.setdefault(p.category.slug, []).append(p)
        popularity = [(p, (3 if "budget" in p.tags else 1.5) + (2 if p.sale_price else 0) + (1.5 if p.category.slug in ("chuot", "ban-phim", "tai-nghe", "lot-chuot") else 0.3)) for p in products]
        total_w = sum(w for _, w in popularity)
        methods = {m.code: m for m in DeliveryMethod.objects.all()}
        coupons = list(Coupon.objects.exclude(code="WELCOME10"))
        now = timezone.now()
        admin = User.objects.filter(is_superuser=True).first()
        demo = next(u for u in users if u.username == "demo")
        sold = {p.pk: 0 for p in products}

        def weighted_product():
            r = self.rnd.uniform(0, total_w)
            for p, w in popularity:
                r -= w
                if r <= 0:
                    return p
            return products[0]

        self.stdout.write(f"Generating {n_orders} orders…")
        for k in range(n_orders):
            # growth trend: more orders in recent weeks (+ weekend bump)
            age_days = 180 * (self.rnd.random() ** 1.35)
            created = now - timedelta(days=age_days, hours=self.rnd.randint(0, 14), minutes=self.rnd.randint(0, 59))
            if created.weekday() >= 5 and self.rnd.random() < 0.15:
                created -= timedelta(hours=2)
            if k < 6:  # make sure the demo account has history
                user = demo
                created = now - timedelta(days=[3, 12, 25, 40, 70, 1][k])
            elif self.rnd.random() < 0.72:
                user = self.rnd.choice([u for u in users if u.date_joined <= created] or users)
            else:
                user = None
            anchor = weighted_product()
            basket = {anchor.pk: anchor}
            if self.rnd.random() < 0.48:
                # a complement category can be empty (e.g. a test catalogue) — fall back to the anchor's own
                comp_cat = self.rnd.choice([c for c in COMPLEMENTS[anchor.category.slug] if by_cat.get(c)] or [anchor.category.slug])
                comp = self.rnd.choice(by_cat[comp_cat])
                # brand affinity: gamers often match brands
                same_brand = [p for p in by_cat[comp_cat] if p.brand_id == anchor.brand_id]
                if same_brand and self.rnd.random() < 0.45:
                    comp = self.rnd.choice(same_brand)
                basket[comp.pk] = comp
            if self.rnd.random() < 0.14:
                extra = weighted_product()
                basket[extra.pk] = extra
            lines = [(p, 2 if (p.category.slug == "lot-chuot" and self.rnd.random() < 0.1) else 1) for p in basket.values()]
            subtotal = sum(p.current_price * q for p, q in lines)

            province = "TP. Hồ Chí Minh" if user == demo else self._pick_province()
            if province in ("TP. Hồ Chí Minh", "Hà Nội") and self.rnd.random() < 0.22:
                method = methods["express"]
            elif province == "TP. Hồ Chí Minh" and self.rnd.random() < 0.1:
                method = methods["pickup"]
            else:
                method = methods["standard"]
            coupon = None
            discount = 0
            if self.rnd.random() < 0.18:
                c = self.rnd.choice(coupons)
                if subtotal >= c.min_order:
                    coupon, discount = c, c.discount_for(subtotal)
            from apps.orders.services import shipping_fee
            ship = shipping_fee(method, province, subtotal, sum(p.weight_grams * q for p, q in lines), coupon)
            pay = self.rnd.choices(["cod", "vnpay", "momo", "bank"], weights=[45, 30, 15, 10])[0]

            age = (now - created).days
            if age > 10:
                status = self.rnd.choices(["completed", "delivered", "cancelled", "returned"], weights=[78, 12, 8, 2])[0]
            elif age > 4:
                status = self.rnd.choices(["delivered", "shipping", "completed", "cancelled"], weights=[40, 25, 25, 10])[0]
            else:
                status = self.rnd.choices(["pending", "confirmed", "packing", "shipping", "cancelled"], weights=[30, 25, 20, 20, 5])[0]
            if pay == "cod":
                pstatus = "paid" if status in ("delivered", "completed") else "unpaid"
            elif status == "cancelled" and self.rnd.random() < 0.5:
                pstatus = "failed"
            elif status in ("returned",):
                pstatus = "refunded"
            elif pay == "bank" and status == "pending":
                pstatus = "unpaid"
            else:
                pstatus = "paid"

            name = f"{user.last_name} {user.first_name}" if user else f"{self.rnd.choice(LAST)} {self.rnd.choice(MIDDLE)} {self.rnd.choice(FIRST)}"
            wards = WARDS.get(province, ["Phường Trung tâm"])
            o = Order(
                user=user, full_name=name, email=user.email if user else f"guest{k}@example.com", phone=(user.phone if user and user.phone else f"09{self.rnd.randint(10000000, 99999999)}"),
                province=province, ward=self.rnd.choice(wards), street=f"{self.rnd.randint(1, 450)} {self.rnd.choice(['Lê Lợi', 'Nguyễn Trãi', 'Điện Biên Phủ', 'Cách Mạng Tháng 8', 'Trần Hưng Đạo', 'Võ Văn Tần', 'Lý Thường Kiệt'])}",
                delivery_method=method, subtotal=subtotal, shipping_fee=ship, discount=discount, total=max(0, subtotal - discount + ship), coupon=coupon,
                status=status, payment_method=pay, payment_status=pstatus, paid_at=created + timedelta(minutes=5) if pstatus in ("paid", "refunded") else None,
                carrier="GHN" if method.code == "standard" else "Ahamove" if method.code == "express" else "", tracking_number=(f"GHN{self.rnd.randint(10**8, 10**9)}" if method.code == "standard" else f"AHM{240000 + k}" if method.code == "express" else "") if status in ("shipping", "delivered", "completed") else "",
            )
            o.save()
            Order.objects.filter(pk=o.pk).update(created_at=created)
            OrderItem.objects.bulk_create([OrderItem(order=o, product=p, product_name=p.name, sku=p.sku, category_name=p.category.name, unit_price=p.current_price, unit_cost=p.cost_price, quantity=q) for p, q in lines])
            flow = ["pending", "confirmed", "packing", "shipping", "delivered", "completed"]
            steps = flow[: flow.index(status) + 1] if status in flow else ["pending", status]
            for j, s in enumerate(steps):
                h = OrderStatusHistory.objects.create(order=o, status=s, changed_by=admin if j else user, note="Khách đặt hàng" if j == 0 else "")
                OrderStatusHistory.objects.filter(pk=h.pk).update(created_at=created + timedelta(hours=j * 8))
            if pay in ("vnpay", "momo") and pstatus != "unpaid":
                Payment.objects.create(order=o, provider=pay, gateway="mock", txn_ref=f"{o.code}-{k:04x}", amount=o.total,
                                       status="success" if pstatus in ("paid", "refunded") else "failed", response_code="00" if pstatus != "failed" else "51",
                                       gateway_txn_no=str(self.rnd.randint(10**7, 10**8)))
            if status not in ("cancelled", "returned"):
                for p, q in lines:
                    sold[p.pk] += q
            # reviews for delivered/completed orders
            if user and status in ("completed", "delivered") and self.rnd.random() < 0.45:
                p = lines[0][0]
                if not Review.objects.filter(product=p, user=user).exists():
                    rating = self.rnd.choices([5, 4, 3, 2], weights=[62, 27, 8, 3])[0]
                    r = Review.objects.create(product=p, user=user, rating=rating, comment=self.rnd.choice(REVIEW_TEXT[rating]), is_verified_purchase=True,
                                              title={5: "Tuyệt vời", 4: "Hài lòng", 3: "Tạm ổn", 2: "Chưa ưng"}[rating])
                    Review.objects.filter(pk=r.pk).update(created_at=created + timedelta(days=self.rnd.randint(3, 9)))
        for p in products:
            Product.objects.filter(pk=p.pk).update(sold_count=sold[p.pk] + self.rnd.randint(5, 60))

    def _behaviour(self, products, users):
        now = timezone.now()
        self.stdout.write("Generating visits, views, searches, chat logs…")
        visits = []
        sources = ["direct", "google", "facebook", "tiktok", "referral", "youtube", "zalo"]
        for d in range(181):
            day = (timezone.localtime() - timedelta(days=d)).date()
            n = int(60 + 140 * (1 - d / 181) ** 1.3 + self.rnd.randint(-15, 15) + (25 if day.weekday() >= 5 else 0))
            for i in range(max(20, n)):
                visits.append(SiteVisit(session_key=f"s{d:03d}{i:04d}{self.rnd.randint(0, 9999):04d}", day=day,
                                        source=self.rnd.choices(sources, weights=[30, 28, 18, 12, 4, 5, 3])[0]))
        SiteVisit.objects.bulk_create(visits, batch_size=2000, ignore_conflicts=True)

        views = []
        for _ in range(6000):
            p = self.rnd.choice(products)
            u = self.rnd.choice(users) if self.rnd.random() < 0.5 else None
            views.append(ProductView(product=p, user=u, session_key=f"v{self.rnd.randint(0, 3000)}"))
        ProductView.objects.bulk_create(views, batch_size=2000)
        ids = list(ProductView.objects.order_by("-id").values_list("id", flat=True)[:6000])
        for chunk_start in range(0, len(ids), 500):
            chunk = ids[chunk_start: chunk_start + 500]
            ProductView.objects.filter(id__in=chunk).update(created_at=now - timedelta(days=self.rnd.randint(0, 60), hours=self.rnd.randint(0, 23)))
        for p in products:
            Product.objects.filter(pk=p.pk).update(view_count=ProductView.objects.filter(product=p).count() * 3)

        logs = []
        for _ in range(900):
            q = self.rnd.choice(SEARCHES) if self.rnd.random() < 0.88 else self.rnd.choice(ZERO_SEARCHES)
            logs.append(SearchLog(query=q, results=0 if q in ZERO_SEARCHES else self.rnd.randint(2, 12)))
        SearchLog.objects.bulk_create(logs)
        for i, s in enumerate(SearchLog.objects.all()):
            if i % 3 == 0:
                SearchLog.objects.filter(pk=s.pk).update(created_at=now - timedelta(days=self.rnd.randint(0, 89)))

        msgs = []
        for i in range(160):
            text, intent = self.rnd.choice(CHAT_SAMPLES)
            sk = f"chat{i // 2}"
            msgs.append(ChatMessage(session_key=sk, role="user", text=text, intent=intent))
            msgs.append(ChatMessage(session_key=sk, role="bot", text="(demo)", intent=intent))
        ChatMessage.objects.bulk_create(msgs)
