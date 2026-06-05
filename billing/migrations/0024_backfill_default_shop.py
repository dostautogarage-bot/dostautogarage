from django.conf import settings
from django.db import migrations


DEFAULT_SHOP_NAME = "Dost Auto Garage"
DEFAULT_SHOP_CODE = "default-shop"


def backfill_default_shop(apps, schema_editor):
    Shop = apps.get_model('billing', 'Shop')
    ShopSettings = apps.get_model('billing', 'ShopSettings')
    SettingsModel = apps.get_model('billing', 'Settings')
    Product = apps.get_model('billing', 'Product')
    Invoice = apps.get_model('billing', 'Invoice')
    Expense = apps.get_model('billing', 'Expense')
    ShopMembership = apps.get_model('billing', 'ShopMembership')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    default_shop, _ = Shop.objects.get_or_create(
        code=DEFAULT_SHOP_CODE,
        defaults={
            'name': DEFAULT_SHOP_NAME,
            'is_active': True,
        },
    )

    settings_map = {
        row.key: row
        for row in SettingsModel.objects.all()
    }

    company_name = settings_map.get('company_name').value if settings_map.get('company_name') else DEFAULT_SHOP_NAME
    company_email = settings_map.get('company_email').value if settings_map.get('company_email') else ''
    company_phone_1 = settings_map.get('company_phone_1').value if settings_map.get('company_phone_1') else ''
    company_phone_2 = settings_map.get('company_phone_2').value if settings_map.get('company_phone_2') else ''
    company_address = settings_map.get('company_address').value if settings_map.get('company_address') else ''
    invoice_prefix = settings_map.get('invoice_prefix').value if settings_map.get('invoice_prefix') else 'KNJ'
    invoice_footer = settings_map.get('invoice_footer').value if settings_map.get('invoice_footer') else ''

    shop_settings, created = ShopSettings.objects.get_or_create(
        shop=default_shop,
        defaults={
            'company_name': company_name,
            'company_email': company_email or None,
            'company_phone_1': company_phone_1 or None,
            'company_phone_2': company_phone_2 or None,
            'company_address': company_address or None,
            'invoice_prefix': invoice_prefix or 'KNJ',
            'invoice_footer': invoice_footer or None,
        },
    )

    signature_setting = settings_map.get('signature')
    if signature_setting and getattr(signature_setting, 'signature', None) and not shop_settings.signature:
        shop_settings.signature = signature_setting.signature
        shop_settings.save(update_fields=['signature'])

    Product.objects.filter(shop__isnull=True).update(shop=default_shop)
    Invoice.objects.filter(shop__isnull=True).update(shop=default_shop)
    Expense.objects.filter(shop__isnull=True).update(shop=default_shop)

    Invoice.objects.filter(company_name_snapshot__isnull=True).update(
        company_name_snapshot=shop_settings.company_name,
        company_email_snapshot=shop_settings.company_email,
        company_phone_1_snapshot=shop_settings.company_phone_1,
        company_phone_2_snapshot=shop_settings.company_phone_2,
        company_address_snapshot=shop_settings.company_address,
        invoice_prefix_snapshot=shop_settings.invoice_prefix,
    )

    for user in User.objects.filter(is_active=True):
        role = 'SHOP_SUPER_ADMIN' if getattr(user, 'is_superuser', False) else 'SHOP_ADMIN'
        ShopMembership.objects.get_or_create(
            user=user,
            shop=default_shop,
            defaults={
                'role': role,
                'is_active': True,
            },
        )


def reverse_backfill_default_shop(apps, schema_editor):
    Shop = apps.get_model('billing', 'Shop')
    ShopMembership = apps.get_model('billing', 'ShopMembership')
    ShopSettings = apps.get_model('billing', 'ShopSettings')
    Product = apps.get_model('billing', 'Product')
    Invoice = apps.get_model('billing', 'Invoice')
    Expense = apps.get_model('billing', 'Expense')

    try:
        default_shop = Shop.objects.get(code=DEFAULT_SHOP_CODE)
    except Shop.DoesNotExist:
        return

    Product.objects.filter(shop=default_shop).update(shop=None)
    Invoice.objects.filter(shop=default_shop).update(
        shop=None,
        company_name_snapshot=None,
        company_email_snapshot=None,
        company_phone_1_snapshot=None,
        company_phone_2_snapshot=None,
        company_address_snapshot=None,
        invoice_prefix_snapshot=None,
    )
    Expense.objects.filter(shop=default_shop).update(shop=None)
    ShopMembership.objects.filter(shop=default_shop).delete()
    ShopSettings.objects.filter(shop=default_shop).delete()
    default_shop.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0023_shop_alter_invoice_options_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_default_shop, reverse_backfill_default_shop),
    ]

# Made with Bob
