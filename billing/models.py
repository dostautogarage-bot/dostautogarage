from django.conf import settings
from django.db import models
from django.utils import timezone
import hashlib

def signature_upload_path(instance, filename):
    return f'signatures/{filename}'

class Settings(models.Model):
	key = models.CharField(max_length=100, unique=True)
	value = models.CharField(max_length=255)
	signature = models.ImageField(upload_to=signature_upload_path, blank=True, null=True)

	def __str__(self):
		return f"{self.key}: {self.value}"


class Product(models.Model):
	name = models.CharField(max_length=100, db_index=True)
	part_number = models.CharField(max_length=100, unique=True, default='', db_index=True)
	price = models.DecimalField(max_digits=10, decimal_places=2)
	stock = models.DecimalField(max_digits=10, decimal_places=2, default=0)

	def __str__(self):
		return self.name


class Invoice(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    invoice_number = models.PositiveIntegerField(unique=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices'
    )
    vehicle_number = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    mechanic_name = models.CharField(max_length=255, blank=True, null=True)

    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, blank=True, null=True)
    ran_kilometer = models.PositiveIntegerField(null=True, blank=True)

    customer_name = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    customer_phone = models.CharField(max_length=15, null=True, blank=True, db_index=True)

    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('COMPLETED', 'Completed'),
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED', db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-invoice_number']

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
        discount = self.discount_amount or 0
        return self.grand_total - discount  # Subtract discount from grand total

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

    @property
    def public_token(self):
        secret = settings.SECRET_KEY
        return hashlib.sha256(f"{self.pk}{secret}".encode()).hexdigest()[:16]

    @property
    def whatsapp_message(self):
        """Generates a detailed text report for WhatsApp sharing."""
        from django.utils.encoding import smart_str
        from urllib.parse import quote

        msg = f"*DOST AUTO GARAGE*\n"
        msg += f"--------------------------\n"
        msg += f"*Invoice:* #{self.formatted_invoice_number}\n"
        msg += f"*Date:* {self.created_at.strftime('%d-%m-%Y')}\n"
        if self.vehicle_number:
            msg += f"*Vehicle:* {self.vehicle_number.upper()}\n"
        if self.mechanic_name:
            msg += f"*Mechanic:* {self.mechanic_name.upper()}\n"
        if self.ran_kilometer:
            msg += f"*Service KM:* {self.ran_kilometer} KM\n"
        msg += f"--------------------------\n"
        
        msg += f"*ITEMS:*\n"
        for item in self.items.all():
            msg += f"- {item.product.name.upper()} ({item.quantity}): Rs.{item.total_price}\n"
        
        other_charges = self.other_charges.all()
        if other_charges:
            msg += f"\n*OTHER CHARGES:*\n"
            for oc in other_charges:
                msg += f"- {oc.name.upper()}: Rs.{oc.amount}\n"
        
        msg += f"*Subtotal:* Rs.{self.total + self.other_charges_total}\n"
        discount = self.discount_amount or 0
        if discount > 0:
            msg += f"*Discount:* Rs.{discount}\n"
        msg += f"*TOTAL DUE:* *Rs.{self.balance_amount}*\n"
        msg += f"--------------------------\n"
        
        msg += f"\n*View/Download PDF:* \n"
        # The base URL will be added in the template since models don't easily know the domain
        return msg

class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)  # ← changed
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
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


class Expense(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='expenses'
    )
    date = models.DateField()
    property_name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.property_name} - ₹{self.amount}"