"""Map pre-reform province names to the 34 units in force since 1/7/2025."""
from django.db import migrations

# Frozen copy of apps.orders.services.LEGACY_PROVINCES at the time of writing
LEGACY = {
    "Bình Dương": "TP. Hồ Chí Minh", "Bà Rịa - Vũng Tàu": "TP. Hồ Chí Minh",
    "Hà Giang": "Tuyên Quang", "Yên Bái": "Lào Cai", "Bắc Kạn": "Thái Nguyên",
    "Vĩnh Phúc": "Phú Thọ", "Hoà Bình": "Phú Thọ", "Hòa Bình": "Phú Thọ", "Bắc Giang": "Bắc Ninh",
    "Thái Bình": "Hưng Yên", "Hải Dương": "Hải Phòng", "Hà Nam": "Ninh Bình", "Nam Định": "Ninh Bình",
    "Quảng Bình": "Quảng Trị", "Quảng Nam": "Đà Nẵng", "Kon Tum": "Quảng Ngãi", "Bình Định": "Gia Lai",
    "Ninh Thuận": "Khánh Hòa", "Khánh Hoà": "Khánh Hòa", "Đắk Nông": "Lâm Đồng", "Bình Thuận": "Lâm Đồng",
    "Phú Yên": "Đắk Lắk", "Bình Phước": "Đồng Nai", "Long An": "Tây Ninh", "Sóc Trăng": "Cần Thơ",
    "Hậu Giang": "Cần Thơ", "Bến Tre": "Vĩnh Long", "Trà Vinh": "Vĩnh Long", "Tiền Giang": "Đồng Tháp",
    "Bạc Liêu": "Cà Mau", "Kiên Giang": "An Giang", "Thừa Thiên Huế": "Huế", "Thanh Hoá": "Thanh Hóa",
}


def forwards(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Address = apps.get_model("accounts", "Address")
    DeliveryMethod = apps.get_model("orders", "DeliveryMethod")
    for old, new in LEGACY.items():
        Order.objects.filter(province=old).update(province=new)
        Address.objects.filter(province=old).update(province=new)
    for m in DeliveryMethod.objects.exclude(only_provinces=""):
        names = []
        for p in m.only_provinces.split(","):
            p = LEGACY.get(p.strip(), p.strip())
            if p and p not in names:
                names.append(p)
        m.only_provinces = ", ".join(names)
        m.save(update_fields=["only_provinces"])


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0002_alter_order_district"),
        ("accounts", "0002_alter_address_district_alter_address_ward"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
