from django.contrib import admin

from .models import Product, Invoice, InvoiceItem, Settings
@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
	list_display = ("key", "value")

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
	list_display = ("name", "price", "stock")
	search_fields = ("name",)

class InvoiceItemInline(admin.TabularInline):
	model = InvoiceItem
	extra = 1

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
	list_display = ("id", "created_at", "created_by", "total")
	list_filter = ("created_by",)
	search_fields = ("invoice_number", "customer_name", "customer_phone", "created_by__username")
	inlines = [InvoiceItemInline]
	readonly_fields = ("total",)
