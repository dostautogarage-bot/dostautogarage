# Generated migration
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0012_rename_vehicle_details_to_vehicle_number'),
    ]

    operations = [
        migrations.AlterField(
            model_name='product',
            name='stock',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name='invoiceitem',
            name='quantity',
            field=models.DecimalField(decimal_places=2, max_digits=10),
        ),
    ]
