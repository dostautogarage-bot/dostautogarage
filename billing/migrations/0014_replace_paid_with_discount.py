# Generated migration
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0013_decimal_quantities'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='invoice',
            name='paid_amount',
        ),
        migrations.AddField(
            model_name='invoice',
            name='discount_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
