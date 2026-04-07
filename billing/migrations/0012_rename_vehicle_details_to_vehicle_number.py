# Generated manually for renaming vehicle_details to vehicle_number

from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0011_settings_signature'),
    ]

    operations = [
        migrations.RenameField(
            model_name='invoice',
            old_name='vehicle_details',
            new_name='vehicle_number',
        ),
    ]