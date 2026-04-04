from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0008_invoice_created_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='part_number',
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
    ]
