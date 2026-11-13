from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def stamp_categories(apps, schema_editor):
    """Fill the new snapshot from the product each existing line still links to."""
    OrderItem = apps.get_model("orders", "OrderItem")
    Product = apps.get_model("catalog", "Product")
    OrderItem.objects.filter(product__isnull=False).update(
        category_name=Subquery(Product.objects.filter(pk=OuterRef("product_id")).values("category__name")[:1])
    )


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0001_initial"),
        ("orders", "0004_history_ordering_tiebreak"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="category_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.RunPython(stamp_categories, migrations.RunPython.noop),
    ]
