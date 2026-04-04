from django.conf import settings
from django.db import models

def signature_upload_path(instance, filename):
    return f'signatures/{filename}'

class Settings(models.Model):
	key = models.CharField(max_length=100, unique=True)
	value = models.CharField(max_length=255)
	signature = models.ImageField(upload_to=signature_upload_path, blank=True, null=True)

	def __str__(self):
		return f"{self.key}: {self.value}"


class Product(models.Model):
	name = models.CharField(max_length=100)
	part_number = models.CharField(max_length=100, default='')
	price = models.DecimalField(max_digits=10, decimal_places=2)
	stock = models.PositiveIntegerField(default=0)

	def __str__(self):
		return self.name




class Invoice(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    invoice_number = models.PositiveIntegerField(unique=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices'
    )
    vehicle_details = models.CharField(max_length=255, blank=True)

    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    next_due_date = models.DateField(null=True, blank=True)
    ran_kilometer = models.PositiveIntegerField(null=True, blank=True)

    customer_name = models.CharField(max_length=100, null=True, blank=True)
    customer_phone = models.CharField(max_length=15, null=True, blank=True)

    def __str__(self):
        return f"Invoice #{self.invoice_number}"

    @property
    def total(self):
        return sum(item.total_price for item in self.items.all())

    @property
    def other_charges_total(self):
        return sum(c.amount for c in self.other_charges.all())

    @property
    def grand_total(self):
        return self.total + self.other_charges_total

    @property
    def balance_amount(self):
        return self.grand_total - self.paid_amount  # ← now includes other charges

    @property
    def formatted_invoice_number(self):
        prefix = "KNJ"
        try:
            from .models import Settings
            prefix_setting = Settings.objects.get(key='invoice_prefix')
            prefix = prefix_setting.value
        except:
            pass

        return f"{prefix}{self.invoice_number:08d}"

class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)  # ← changed
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)  # Price at time of sale

    @property
    def total_price(self):
        return self.price * self.quantity


class OtherCharge(models.Model):
    invoice = models.ForeignKey(Invoice, related_name='other_charges', on_delete=models.CASCADE)
    name    = models.CharField(max_length=100)
    amount  = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.name} - ₹{self.amount}"