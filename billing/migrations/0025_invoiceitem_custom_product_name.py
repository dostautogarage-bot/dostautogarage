# Generated manually to add custom product name field

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0024_backfill_default_shop'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoiceitem',
            name='custom_product_name',
            field=models.CharField(blank=True, help_text='For products not in stock', max_length=200, null=True),
        ),
        migrations.AlterField(
            model_name='invoiceitem',
            name='product',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='billing.product'),
        ),
    ]

# Made with Bob
