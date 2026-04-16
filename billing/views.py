# -------------------- IMPORTS --------------------
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django import forms
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from datetime import datetime, timedelta
from decimal import Decimal
import os
import hashlib
from django.utils.crypto import get_random_string

from .models import Product, Invoice, InvoiceItem, OtherCharge, Settings, Expense

# ReportLab
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, KeepTogether
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# -------------------- PRODUCT FORMS --------------------
class ProductForm(forms.ModelForm):
    part_number = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='Enter the product part number.'
    )

    class Meta:
        model = Product
        fields = ['name', 'part_number', 'price', 'stock']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={'class': 'form-control'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control'}),
        }


# -------------------- INVOICE FORMS --------------------
class InvoiceItemForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    quantity = forms.DecimalField(
        min_value=Decimal('0.01'),
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )


class BaseInvoiceItemFormSet(forms.BaseFormSet):
    def clean(self):
        if any(self.errors):
            return

        seen_part_numbers = set()
        for form in self.forms:
            if self.can_delete and form.cleaned_data.get('DELETE', False):
                continue
            product = form.cleaned_data.get('product')
            if product and product.part_number:
                part_key = product.part_number.strip().upper()
                if part_key in seen_part_numbers:
                    raise forms.ValidationError('Duplicate products with the same part number are not allowed.')
                seen_part_numbers.add(part_key)


class InvoiceMainForm(forms.ModelForm):
    mechanic_name = forms.CharField(
        required=False,
        label='Mechanic Name',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter Mechanic Name'})
    )
    ran_kilometer = forms.IntegerField(
        required=False,
        label='Service Kilometer',
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = Invoice
        fields = [
            'customer_name',
            'customer_phone',
            'vehicle_number',
            'mechanic_name',
            'discount_amount',
            'ran_kilometer'
        ]
        widgets = {
            'customer_name': forms.TextInput(attrs={'class': 'form-control'}),
            'customer_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'vehicle_number': forms.TextInput(attrs={'class': 'form-control'}),
            'discount_amount': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class ExpenseForm(forms.ModelForm):
    date = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        required=True,
        label='Date'
    )
    property_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='Property'
    )
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        label='Amount'
    )

    class Meta:
        model = Expense
        fields = ['date', 'property_name', 'amount']


# -------------------- SETTINGS FORM --------------------
class CompanySettingsForm(forms.Form):
    company_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter company name'}),
        label='Company Name'
    )
    company_email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter email'}),
        label='Company Email'
    )
    company_phone_1 = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter primary phone'}),
        label='Primary Phone Number'
    )
    company_phone_2 = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter secondary phone (optional)'}),
        label='Secondary Phone Number'
    )
    company_address = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Enter company address'}),
        label='Company Address'
    )
    invoice_prefix = forms.CharField(
        max_length=10,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., INV, KNJ, DST'}),
        label='Invoice Number Prefix'
    )
    invoice_footer = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Footer text for invoices'}),
        label='Invoice Footer Text'
    )
    signature = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        label='Digital Signature',
        help_text='Upload a signature image (PNG, JPG, JPEG) for invoices'
    )


# -------------------- ADMIN MANAGEMENT FORMS --------------------
class AdminCreationForm(UserCreationForm):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
        label='Email Address'
    )
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='First Name'
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='Last Name'
    )

    class Meta:
        model = get_user_model()
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget = forms.PasswordInput(attrs={'class': 'form-control'})
        self.fields['password2'].widget = forms.PasswordInput(attrs={'class': 'form-control'})
        self.fields['password1'].help_text = 'Enter any password'
        self.fields['password2'].help_text = 'Enter the same password for verification'
        # Remove ALL validators from password fields
        self.fields['password1'].validators = []
        self.fields['password2'].validators = []

    def clean(self):
        cleaned_data = self.cleaned_data
        
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        
        # Only validate that passwords match
        if password1 and password2 and password1 != password2:
            self.add_error('password2', 'Passwords do not match.')
        
        return cleaned_data

    def clean_password1(self):
        """Override to skip ALL password validation"""
        return self.cleaned_data.get('password1')

    def clean_password2(self):
        """Override to skip ALL password validation"""
        return self.cleaned_data.get('password2')

    def save(self, commit=True):
        username = self.cleaned_data['username']
        email = self.cleaned_data.get('email')
        first_name = self.cleaned_data['first_name']
        last_name = self.cleaned_data['last_name']
        password = self.cleaned_data['password1']
        
        user = get_user_model()(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_staff=True,
            is_superuser=True
        )
        user.set_password(password)
        
        if commit:
            user.save()
        return user


class AdminEditForm(UserChangeForm):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
        label='Email Address'
    )
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='First Name'
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label='Last Name'
    )
    is_active = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Active'
    )

    class Meta:
        model = get_user_model()
        fields = ('username', 'email', 'first_name', 'last_name', 'is_active')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password'].widget = forms.HiddenInput()
        self.fields.pop('password', None)


# -------------------- PRODUCT VIEWS --------------------
@login_required
@user_passes_test(lambda u: u.is_superuser)
def product_list(request):
    products = Product.objects.all()
    total_product_worth = sum(p.price * p.stock for p in products)
    outofstock_count = Product.objects.filter(stock__lte=0).count()
    return render(request, 'billing/product_list.html', {
        'products': products,
        'total_product_worth': total_product_worth,
        'outofstock_count': outofstock_count
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def product_add(request):
    form = ProductForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('product_list')

    return render(request, 'billing/product_form.html', {'form': form, 'title': 'Add Product'})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)

    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('product_list')

    return render(request, 'billing/product_form.html', {'form': form, 'title': 'Edit Product'})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)

    if request.method == 'POST':
        product.delete()
        return redirect('product_list')

    return render(request, 'billing/product_confirm_delete.html', {'product': product})


@login_required
def expense_list(request):
    admin_filter = request.GET.get('admin', '').strip()
    if request.user.is_superuser:
        expenses = Expense.objects.all().order_by('-date')
        users = get_user_model().objects.filter(is_active=True).order_by('username')
        if admin_filter:
            expenses = expenses.filter(created_by_id=admin_filter)
    else:
        expenses = Expense.objects.filter(created_by=request.user).order_by('-date')
        users = None

    form = ExpenseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        expense = form.save(commit=False)
        expense.created_by = request.user
        expense.save()
        return redirect('expense_list')

    total_expenses = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Pagination logic (like invoice_list)
    try:
        per_page = int(request.GET.get('per_page', 100))
    except (TypeError, ValueError):
        per_page = 100
    if per_page not in [100, 200, 300, 500]:
        per_page = 100
    page_number = request.GET.get('page')
    paginator = Paginator(expenses, per_page)
    page_obj = paginator.get_page(page_number)

    return render(request, 'billing/expense_list.html', {
        'expenses': page_obj.object_list,
        'form': form,
        'users': users,
        'selected_admin': admin_filter,
        'total_expenses': total_expenses,
        'paginator': paginator,
        'page_obj': page_obj,
        'per_page': per_page,
    })


@login_required
def expense_detail(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if not request.user.is_superuser and expense.created_by != request.user:
        return redirect('expense_list')
    return render(request, 'billing/expense_detail.html', {'expense': expense})


@login_required
def expense_edit(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if not request.user.is_superuser and expense.created_by != request.user:
        return redirect('expense_list')
    form = ExpenseForm(request.POST or None, instance=expense)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('expense_list')
    return render(request, 'billing/expense_form.html', {'form': form, 'title': 'Edit Expense'})


@login_required
def expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if not request.user.is_superuser and expense.created_by != request.user:
        return redirect('expense_list')
    if request.method == 'POST':
        expense.delete()
        return redirect('expense_list')
    return render(request, 'billing/expense_confirm_delete.html', {'expense': expense})


# -------------------- INVOICE LIST --------------------
@login_required
@user_passes_test(lambda u: u.is_superuser)
def invoice_list(request):
    query = request.GET.get('q', '').strip()
    creator_id = request.GET.get('creator', '').strip()
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()
    per_page = int(request.GET.get('per_page', 100))
    if per_page not in [100, 200, 300, 500]:
        per_page = 100

    invoices = Invoice.objects.all().order_by('-created_at').select_related('created_by').prefetch_related('items', 'other_charges')
    users = get_user_model().objects.filter(is_active=True).order_by('username')

    if creator_id:
        invoices = invoices.filter(created_by_id=creator_id)

    if query:
        # Get invoice prefix for formatted search
        try:
            prefix = Settings.objects.get(key='invoice_prefix').value.upper()
        except Settings.DoesNotExist:
            prefix = 'KNJ'
        
        search_filters = Q(
            Q(customer_name__icontains=query) |
            Q(customer_phone__icontains=query) |
            Q(created_by__username__icontains=query) |
            Q(created_by__first_name__icontains=query) |
            Q(created_by__last_name__icontains=query)
        )
        
        # Search by ID (primary key)
        if query.isdigit():
            search_filters |= Q(id=query)
        
        # Search by invoice number (numeric part)
        if query.isdigit():
            search_filters |= Q(invoice_number=query)
        
        # Search by formatted invoice number (e.g., KNJ00000001)
        if query.upper().startswith(prefix) and query[len(prefix):].isdigit():
            number_part = int(query[len(prefix):])
            search_filters |= Q(invoice_number=number_part)
        
        invoices = invoices.filter(search_filters)

    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            invoices = invoices.filter(created_at__date__gte=start)
        except ValueError:
            start_date = ''

    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            invoices = invoices.filter(created_at__date__lte=end)
        except ValueError:
            end_date = ''

    paginator = Paginator(invoices, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'billing/invoice_list.html', {
        'invoices': page_obj,
        'query': query,
        'per_page': per_page,
        'users': users,
        'selected_creator': creator_id,
        'start_date': start_date,
        'end_date': end_date,
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def dashboard(request):
    month = request.GET.get('month', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    selected_admin = request.GET.get('admin', '')
    today = datetime.today().date()
    default_start = today - timedelta(days=30)
    default_end = today

    if month:
        try:
            start = datetime.strptime(month + '-01', '%Y-%m-%d').date()
            end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        except ValueError:
            start = default_start
            end = default_end
    else:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else default_start
        except ValueError:
            start = default_start

        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else default_end
        except ValueError:
            end = default_end

        if end < start:
            start, end = end, start

    invoices = Invoice.objects.filter(
        created_at__date__gte=start, 
        created_at__date__lte=end
    ).select_related('created_by').prefetch_related('items', 'other_charges')
    users = get_user_model().objects.filter(is_active=True).order_by('username')

    admin_user = None
    admin_invoices = None
    admin_stats = {}
    if selected_admin:
        try:
            admin_user = get_user_model().objects.get(pk=int(selected_admin))
            admin_invoices = invoices.filter(created_by=admin_user)
        except (ValueError, get_user_model().DoesNotExist):
            admin_user = None
            admin_invoices = None

    invoice_count = invoices.count()
    total_invoice_value = sum(invoice.grand_total for invoice in invoices)
    products_sold = InvoiceItem.objects.filter(invoice__in=invoices).aggregate(total_qty=Sum('quantity'))['total_qty'] or 0
    total_other_charges = OtherCharge.objects.filter(invoice__in=invoices).aggregate(total_amount=Sum('amount'))['total_amount'] or 0
    total_discount = invoices.aggregate(total_discount=Sum('discount_amount'))['total_discount'] or 0
    balance_amount = total_invoice_value - total_discount
    total_expenses = Expense.objects.filter(date__gte=start, date__lte=end).aggregate(total_amount=Sum('amount'))['total_amount'] or Decimal('0')

    if admin_invoices is not None:
        admin_invoice_count = admin_invoices.count()
        admin_products_sold = InvoiceItem.objects.filter(invoice__in=admin_invoices).aggregate(total_qty=Sum('quantity'))['total_qty'] or 0
        admin_other_charges = OtherCharge.objects.filter(invoice__in=admin_invoices).aggregate(total_amount=Sum('amount'))['total_amount'] or 0
        admin_total_discount = admin_invoices.aggregate(total_discount=Sum('discount_amount'))['total_discount'] or 0
        admin_balance_amount = sum(invoice.grand_total for invoice in admin_invoices) - admin_total_discount
        admin_expenses = Expense.objects.filter(created_by=admin_user, date__gte=start, date__lte=end).aggregate(total_amount=Sum('amount'))['total_amount'] or Decimal('0')
        admin_stats = {
            'invoice_count': admin_invoice_count,
            'products_sold': admin_products_sold,
            'other_charges': admin_other_charges,
            'total_discount': admin_total_discount,
            'balance_amount': admin_balance_amount,
            'expenses': admin_expenses,
        }
    else:
        admin_stats = None

    user_counts = invoices.values(
        'created_by__username',
        'created_by__first_name',
        'created_by__last_name'
    ).annotate(count=Count('pk')).order_by('-count')

    user_chart_labels = []
    user_chart_values = []
    for row in user_counts:
        username = row['created_by__username'] or 'Unknown'
        full_name = (row['created_by__first_name'] or row['created_by__last_name'] or '').strip()
        label = full_name or username
        user_chart_labels.append(label)
        user_chart_values.append(row['count'])

    top_products = InvoiceItem.objects.filter(invoice__in=invoices).values('product__name').annotate(total_qty=Sum('quantity')).order_by('-total_qty')[:5]

    return render(request, 'billing/dashboard.html', {
        'start_date': start.strftime('%Y-%m-%d'),
        'end_date': end.strftime('%Y-%m-%d'),
        'invoice_count': invoice_count,
        'month': month,
        'total_invoice_value': total_invoice_value,
        'products_sold': products_sold,
        'total_other_charges': total_other_charges,
        'total_discount': total_discount,
        'balance_amount': balance_amount,
        'user_counts': user_counts,
        'user_chart_labels': user_chart_labels,
        'user_chart_values': user_chart_values,
        'top_products': top_products,
        'users': users,
        'selected_admin': selected_admin,
        'admin_user': admin_user,
        'admin_stats': admin_stats,
        'total_expenses': total_expenses,
    })

from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

@require_POST
def product_add_stock(request, pk):
    product = get_object_or_404(Product, pk=pk)
    add_stock = int(request.POST.get('add_stock', 0))
    if add_stock > 0:
        product.stock += add_stock
        product.save()
    return redirect('product_list')

from django.contrib import messages

# -------------------- CREATE INVOICE --------------------
import json

@login_required
@user_passes_test(lambda u: u.is_superuser)
def invoice_create(request):
    ItemFormSet = forms.formset_factory(
        InvoiceItemForm,
        formset=BaseInvoiceItemFormSet,
        extra=1,
        min_num=0,
        validate_min=True,
        can_delete=False
    )

    formset   = ItemFormSet(request.POST or None)
    main_form = InvoiceMainForm(request.POST or None)

    if request.method == 'POST':
        charges_raw = request.POST.get('other_charges', '[]')
        try:
            total_charges_posted = len(json.loads(charges_raw))
        except:
            total_charges_posted = 0

        # Check if formset is valid AND (either formset has items OR charges exist)
        if formset.is_valid() and main_form.is_valid():
            total_items_posted = sum(1 for f in formset if f.cleaned_data and f.cleaned_data.get('product'))
            
            if total_items_posted == 0 and total_charges_posted == 0:
                messages.error(request, "Please add at least one product or one charge.")
                return render(request, 'billing/invoice_form.html', {'formset': formset, 'main_form': main_form, 'products': Product.objects.all()})

            selected_parts = set()
            duplicate_found = False

            for form in formset:
                if not form.cleaned_data:
                    continue
                product = form.cleaned_data.get('product')
                if product and product.part_number:
                    part_key = product.part_number.strip().upper()
                    if part_key in selected_parts:
                        form.add_error('product', 'Duplicate product part number not allowed.')
                        duplicate_found = True
                    else:
                        selected_parts.add(part_key)

            if duplicate_found:
                return render(request, 'billing/invoice_form.html', {
                    'formset'  : formset,
                    'main_form': main_form,
                    'products' : Product.objects.all()
                })

            # ── Invoice number ───────────────────────────────────────────────
            last_invoice = Invoice.objects.order_by('-invoice_number').first()
            next_number  = (last_invoice.invoice_number if last_invoice else 0) + 1

            invoice = main_form.save(commit=False)
            invoice.invoice_number = next_number
            invoice.created_by = request.user
            invoice.discount_amount = main_form.cleaned_data.get('discount_amount') or 0
            invoice.save()

            # ── Invoice items ────────────────────────────────────────────────
            for form in formset:
                if not form.cleaned_data:
                    continue

                product  = form.cleaned_data.get('product')
                quantity = form.cleaned_data.get('quantity')

                if not product or not quantity:
                    continue

                if product.stock < quantity:
                    invoice.delete()
                    available = product.stock.quantize(Decimal('0.01')).normalize() if isinstance(product.stock, Decimal) else product.stock
                    form.add_error('quantity', f'Only {available} available for {product.name}')
                    return render(request, 'billing/invoice_form.html', {
                        'formset'  : formset,
                        'main_form': main_form,
                        'products' : Product.objects.all()
                    })

                InvoiceItem.objects.create(
                    invoice  = invoice,
                    product  = product,
                    quantity = quantity,
                    price    = product.price
                )

                product.stock -= quantity
                product.save()

            # ── Other charges ────────────────────────────────────────────────
            charges_raw = request.POST.get('other_charges', '[]')
            try:
                charges = json.loads(charges_raw)
                for charge in charges:
                    name   = charge.get('name', '').strip()
                    amount = charge.get('amount', 0)
                    if name and float(amount) > 0:
                        OtherCharge.objects.create(
                            invoice = invoice,
                            name    = name,
                            amount  = amount
                        )
            except (ValueError, KeyError, json.JSONDecodeError):
                pass  # silently skip malformed charges

            messages.success(
                request,
                f'Invoice #{invoice.formatted_invoice_number} created successfully.'
            )
            return redirect('invoice_detail', pk=invoice.pk)

    return render(request, 'billing/invoice_form.html', {
        'formset'  : formset,
        'main_form': main_form,
        'products' : Product.objects.all()  # include all products for search
    })


# -------------------- INVOICE DETAIL --------------------
@login_required
@user_passes_test(lambda u: u.is_superuser)
def invoice_detail(request, pk):
    return render(request, 'billing/invoice_detail.html', {
        'invoice': get_object_or_404(Invoice, pk=pk)
    })


# -------------------- DELETE --------------------
@login_required
@user_passes_test(lambda u: u.is_superuser)
def invoice_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    if request.method == 'POST':
        invoice.delete()
        return redirect('invoice_list')

    return render(request, 'billing/invoice_confirm_delete.html', {'invoice': invoice})


# -------------------- INVOICE EDIT --------------------
@login_required
@user_passes_test(lambda u: u.is_superuser) 
def invoice_edit(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    ItemFormSet = forms.formset_factory(
        InvoiceItemForm,
        formset=BaseInvoiceItemFormSet,
        extra=1,
        min_num=0,
        validate_min=True,
        can_delete=True
    )
    formset = ItemFormSet(request.POST or None, initial=[{'product': item.product.pk, 'quantity': item.quantity} for item in invoice.items.all()])
    main_form = InvoiceMainForm(request.POST or None, instance=invoice)
    other_charges = list(invoice.other_charges.all())

    if request.method == 'POST':
        charges_raw = request.POST.get('other_charges', '[]')
        try:
            total_charges_posted = len(json.loads(charges_raw))
        except:
            total_charges_posted = 0

        if formset.is_valid() and main_form.is_valid():
            total_items_posted = sum(1 for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False) and f.cleaned_data.get('product'))

            if total_items_posted == 0 and total_charges_posted == 0:
                messages.error(request, "Please add at least one product or one charge.")
                return render(request, 'billing/invoice_form.html', {'formset': formset, 'main_form': main_form, 'products': Product.objects.all(), 'editing': True, 'invoice': invoice, 'other_charges': other_charges})

        selected_parts = set()
        duplicate_found = False

        for form in formset:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                product = form.cleaned_data.get('product')
                if product and product.part_number:
                    part_key = product.part_number.strip().upper()
                    if part_key in selected_parts:
                        form.add_error('product', 'Duplicate product part number not allowed.')
                        duplicate_found = True
                    else:
                        selected_parts.add(part_key)

        if duplicate_found:
            return render(request, 'billing/invoice_form.html', {'formset': formset, 'main_form': main_form, 'products': Product.objects.all(), 'editing': True, 'invoice': invoice, 'other_charges': other_charges})

        # Update main invoice
        main_form.save()

        # Handle invoice items based on the change delta instead of treating edit like a new invoice.
        old_quantities = {}
        for item in invoice.items.all():
            old_quantities[item.product_id] = old_quantities.get(item.product_id, Decimal('0')) + item.quantity

        new_items = []
        new_product_ids = set()
        for form in formset:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                product = form.cleaned_data.get('product')
                quantity = form.cleaned_data.get('quantity')
                if product and quantity > 0:
                    new_items.append((form, product, quantity))
                    new_product_ids.add(product.pk)

        # Validate stock without changing it yet
        for form, product, quantity in new_items:
            old_quantity = old_quantities.get(product.pk, Decimal('0'))
            delta = Decimal(quantity) - old_quantity
            if delta > 0 and product.stock < delta:
                available = product.stock.quantize(Decimal('0.01')).normalize() if isinstance(product.stock, Decimal) else product.stock
                form.add_error('quantity', f'Only {available} available for {product.name}')
                return render(request, 'billing/invoice_form.html', {
                    'formset': formset,
                    'main_form': main_form,
                    'products': Product.objects.all(),
                    'editing': True,
                    'invoice': invoice,
                    'other_charges': other_charges
                })

        delta_messages = []

        # Restore stock for deleted products or reduced quantities
        for product_id, old_quantity in old_quantities.items():
            if product_id not in new_product_ids:
                product = Product.objects.get(pk=product_id)
                product.stock += old_quantity
                product.save()
                delta_messages.append(f"{product.name} +{old_quantity}")

        invoice.items.all().delete()  # Clear existing items

        # Save updated items and apply only the stock delta
        for form, product, quantity in new_items:
            old_quantity = old_quantities.get(product.pk, Decimal('0'))
            delta = Decimal(quantity) - old_quantity
            if delta > 0:
                product.stock -= delta
                delta_messages.append(f"{product.name} -{delta}")
            elif delta < 0:
                product.stock += abs(delta)
                delta_messages.append(f"{product.name} +{abs(delta)}")
            product.save()
            InvoiceItem.objects.create(invoice=invoice, product=product, quantity=quantity, price=product.price)

        # Handle other charges - delete existing and recreate
        invoice.other_charges.all().delete()  # Clear existing charges
        charges_raw = request.POST.get('other_charges', '[]')
        try:
            charges = json.loads(charges_raw)
            for charge in charges:
                name = charge.get('name', '').strip()
                amount = charge.get('amount', 0)
                if name and float(amount) > 0:
                    OtherCharge.objects.create(invoice=invoice, name=name, amount=amount)
        except (ValueError, KeyError, json.JSONDecodeError):
            pass

        messages.success(request, f'Invoice #{invoice.formatted_invoice_number} updated successfully.')
        return redirect('invoice_detail', pk=invoice.pk)

    return render(request, 'billing/invoice_form.html', {
        'formset': formset, 
        'main_form': main_form, 
        'products': Product.objects.all(), 
        'editing': True, 
        'invoice': invoice, 
        'other_charges': other_charges
    })


# -------------------- PREMIUM PDF --------------------
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
import os


from django.http import JsonResponse
from django.db.models import Q
from .models import Product  # adjust import



def product_search_api(request):
    query = request.GET.get('q', '').strip()
    if not query:
        products = Product.objects.all()[:20]  # show top 20 on empty
    else:
        products = Product.objects.filter(
            Q(name__icontains=query)
        ).order_by('name')[:30]   # max 30 results

    data = [
        {
            'id':    p.pk,
            'name':  p.name,
            'price': str(p.price),
            'stock': p.stock,
        }
        for p in products
    ]
    return JsonResponse(data, safe=False)
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
from .models import Product  # adjust import path


@login_required
@require_GET
def product_list_api(request):
    """
    GET /api/products/?q=oil&page=1&per_page=25&stock_filter=zero
    """
    query        = request.GET.get('q', '').strip()
    stock_filter = request.GET.get('stock_filter', '').strip()
    page         = max(1, int(request.GET.get('page', 1)))
    per_page     = int(request.GET.get('per_page', 100))
    if per_page not in [100, 200, 300, 500]:
        per_page = 100

    qs = Product.objects.all().order_by('name')

    if stock_filter == 'zero':
        qs = qs.filter(stock__lte=0)

    if query:
        qs = qs.filter(
            Q(name__icontains=query) |
            Q(part_number__icontains=query)
        )

    total    = qs.count()
    offset   = (page - 1) * per_page
    products = qs[offset: offset + per_page]

    return JsonResponse({
        'products': [
            {
                'id':    p.pk,
                'name':  p.name,
                'part_number': p.part_number,
                'price': str(p.price),
                'stock': p.stock,
            }
            for p in products
        ],
        'total':    total,
        'page':     page,
        'per_page': per_page,
    })


# ── Add to urls.py ─────────────────────────────────────────────────────────────
# path('api/products/', views.product_list_api, name='product_list_api'),
def get_invoice_token(invoice_id):
    """Generate a unique secret token for an invoice based on its ID and SECRET_KEY."""
    secret = settings.SECRET_KEY
    return hashlib.sha256(f"{invoice_id}{secret}".encode()).hexdigest()[:16]


def public_invoice_pdf(request, pk, token):
    """View to serve invoice PDF to customers without login using a secure token."""
    invoice = get_object_or_404(Invoice, pk=pk)
    if token != get_invoice_token(invoice.pk):
        return HttpResponse("Invalid Access Token", status=403)
    
    # We just call the existing logic (or refactor)
    return invoice_pdf_logic(request, invoice)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def invoice_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    return invoice_pdf_logic(request, invoice)


def invoice_pdf_logic(request, invoice):
    """Core logic to generate invoice PDF (extracted to be reused by public view)."""
    # Register Professional Font (Segoe UI)
    font_normal = 'Helvetica'
    font_bold   = 'Helvetica-Bold'
    
    try:
        if os.path.exists('C:/Windows/Fonts/segoeui.ttf'):
            pdfmetrics.registerFont(TTFont('SegoeUI', 'C:/Windows/Fonts/segoeui.ttf'))
            pdfmetrics.registerFont(TTFont('SegoeUI-Bold', 'C:/Windows/Fonts/segoeuib.ttf'))
            font_normal = 'SegoeUI'
            font_bold   = 'SegoeUI-Bold'
    except:
        pass

    invoice_number = invoice.formatted_invoice_number
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{invoice_number}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    elements = []
    
    # Custom styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'MainTitle',
        parent=styles['Heading1'],
        fontName=font_bold,
        fontSize=24,
        textColor=colors.HexColor("#1e293b"),
        alignment=0 # Left aligned
    )
    company_name_style = ParagraphStyle(
        'CompName',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=22,
        textColor=colors.HexColor("#2563eb"),
        alignment=2 # Right aligned
    )
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontName=font_normal,
        fontSize=10,
        textColor=colors.HexColor("#475569")
    )
    company_address_style = ParagraphStyle(
        'CompAddr',
        parent=normal_style,
        alignment=2 # Right aligned
    )
    bold_style = ParagraphStyle(
        'CustomBold',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=10,
        textColor=colors.HexColor("#1e293b")
    )

    total              = invoice.total
    other_charges_total = invoice.other_charges_total
    grand_total        = invoice.grand_total
    discount           = invoice.discount_amount
    balance            = invoice.balance_amount
    currency_symbol    = 'Rs.'

    # ---- Get company settings from database ----
    settings_dict = {}
    signature_obj = None
    for s in Settings.objects.all():
        settings_dict[s.key] = s.value
        if s.key == 'signature':
            signature_obj = s
    
    try:
        signature_obj = Settings.objects.get(key='signature')
    except Settings.DoesNotExist:
        pass
    
    company_name = settings_dict.get('company_name', 'DOSTAUTOGARAGE')
    company_email = settings_dict.get('company_email', 'dostautogarage@gmail.com')
    company_phone_1 = settings_dict.get('company_phone_1', '9746519367')
    company_phone_2 = settings_dict.get('company_phone_2', '9745582281')
    company_address = settings_dict.get('company_address', '')
    invoice_footer = settings_dict.get('invoice_footer', 'Thank you for your business!')

    phone_text = company_phone_1
    if company_phone_2:
        phone_text = f"{company_phone_1}, {company_phone_2}"

    # ---------------- HEADER ----------------
    logo_path = os.path.join(settings.BASE_DIR, 'static/logo.png')

    comp_text = f"{company_address}<br/>Email: {company_email}<br/>Phone: {phone_text}"
    
    # Left Header: Invoice Details
    left_header = [
        Paragraph("INVOICE", title_style),
        Spacer(1, 10),
        Paragraph(f"<b>Invoice #:</b> {invoice_number}", bold_style),
        Paragraph(f"<b>Date:</b> {invoice.created_at.strftime('%d %b %Y')}", normal_style)
    ]
    
    # Right Header: Company Details
    right_header = [
        Paragraph(company_name, company_name_style),
        Spacer(1, 4),
        Paragraph(comp_text, company_address_style)
    ]
    
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=40*mm, height=20*mm)
        right_header.insert(0, logo)
        right_header.insert(1, Spacer(1, 10))

    header_table = Table([[left_header, right_header]], colWidths=[250, 250])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 20))
    
    # ---------------- CUSTOMER INFO ----------------
    info_header_style = ParagraphStyle(
        'InfoHeader',
        parent=bold_style,
        fontSize=9,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=4,
        textTransform='uppercase'
    )

    created_by_name = invoice.created_by.get_full_name() or invoice.created_by.username if invoice.created_by else "System"

    # Make the name big and bold, soften the labels
    customer_info = f"<font size='11'><b>{invoice.customer_name.upper() if invoice.customer_name else 'N/A'}</b></font><br/>"
    if invoice.customer_phone:
        customer_info += f"<font color='#64748b'>Phone:</font> {invoice.customer_phone}"
    else:
        customer_info += "<font color='#64748b'>Phone:</font> N/A"
    
    vehicle_info = f"<font color='#64748b'>Vehicle #:</font> <b>{invoice.vehicle_number.upper() if invoice.vehicle_number else 'N/A'}</b><br/>"
    if invoice.mechanic_name:
        vehicle_info += f"<font color='#64748b'>Mechanic:</font> <b>{invoice.mechanic_name.upper()}</b><br/>"
    if invoice.ran_kilometer:
        vehicle_info += f"<font color='#64748b'>Service at:</font> <b>{invoice.ran_kilometer} KM</b><br/>"
    vehicle_info += f"<font color='#64748b'>Prepared by:</font> {created_by_name.title()}"

    info_table = Table([[
        [Paragraph("BILL TO", info_header_style), Paragraph(customer_info, normal_style)],
        [Paragraph("SERVICE DETAILS", info_header_style), Paragraph(vehicle_info, normal_style)]
    ]], colWidths=[240, 260])
    
    info_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('TOPPADDING', (0,0), (-1,-1), 16),
        ('BOTTOMPADDING', (0,0), (-1,-1), 16),
        ('LEFTPADDING', (0,0), (-1,-1), 16),
        ('RIGHTPADDING', (0,0), (-1,-1), 16),
        ('LINEABOVE', (0,0), (-1,-1), 1.5, colors.HexColor("#f1f5f9")),
        ('LINEBELOW', (0,0), (-1,-1), 1.5, colors.HexColor("#e2e8f0")),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 28))

    # ---------------- PRODUCT TABLE ----------------
    data = [["DESCRIPTION", "QTY", "RATE", "AMOUNT"]]

    for item in invoice.items.all():
        data.append([
            item.product.name.upper(),
            str(item.quantity),
            f"{item.price:.2f}",
            f"{item.total_price:.2f}"
        ])

    product_table = Table(data, colWidths=[240, 60, 100, 100])
    styles_table = [
        ('BACKGROUND',    (0,0), (-1,0), colors.HexColor("#1e293b")),
        ('TEXTCOLOR',     (0,0), (-1,0), colors.white),
        ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,0), 10),
        ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE',      (0,1), (-1,-1), 9),
        ('ALIGN',         (0,0), (0,-1), 'LEFT'),
        ('ALIGN',         (1,0), (1,-1), 'CENTER'),
        ('ALIGN',         (2,0), (-1,-1), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('TOPPADDING',    (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,1), (-1,-1), 6),
        ('TOPPADDING',    (0,1), (-1,-1), 6),
        ('LINEBELOW',     (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
    ]
    product_table.setStyle(TableStyle(styles_table))
    elements.append(product_table)

    # ---------------- OTHER CHARGES TABLE ----------------
    other_charges = invoice.other_charges.all()
    if other_charges.exists():
        elements.append(Spacer(1, 15))
        charges_data = [["OTHER CHARGES", "AMOUNT"]]
        for charge in other_charges:
            charges_data.append([
                charge.name.upper(),
                f"{charge.amount:.2f}"
            ])
        charges_table = Table(charges_data, colWidths=[400, 100])
        charges_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0), colors.HexColor("#f1f5f9")),
            ('TEXTCOLOR',     (0,0), (-1,0), colors.HexColor("#475569")),
            ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,-1), 9),
            ('ALIGN',         (0,0), (0,-1), 'LEFT'),
            ('ALIGN',         (1,0), (-1,-1), 'RIGHT'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING',    (0,0), (-1,-1), 6),
            ('LINEBELOW',     (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ]))
        elements.append(charges_table)
        
    elements.append(Spacer(1, 20))

    # ---------------- TOTALS (RIGHT SIDE) ----------------
    totals_data = [
        ["Subtotal:", f"{currency_symbol} {total:.2f}"]
    ]

    if other_charges.exists():
        totals_data.append(["Other Charges:", f"{currency_symbol} {other_charges_total:.2f}"])

    totals_data += [
        ["Discount:", f"{currency_symbol} {discount:.2f}"],
        ["TOTAL DUE:", f"{currency_symbol} {balance:.2f}"]
    ]

    totals_table = Table(totals_data, colWidths=[350, 150])
    totals_table.setStyle(TableStyle([
        ('FONTNAME',   (0,0),  (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,0),  (-1,-1), 10),
        ('ALIGN',      (0,0),  (0,-1), 'RIGHT'),
        ('ALIGN',      (1,0),  (1,-1), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        
        # Total Due Row Bold
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,-1), (-1,-1), 12),
        ('TEXTCOLOR', (0,-1), (-1,-1), colors.HexColor("#2563eb")),
        ('LINEABOVE', (0,-1), (-1,-1), 1.5, colors.HexColor("#e2e8f0")),
        ('TOPPADDING', (0,-1), (-1,-1), 10),
    ]))

    elements.append(totals_table)
    elements.append(Spacer(1, 30))


    # ---------------- FOOTER ----------------
    footer_data = []
    
    # Left side: Thank you message
    left_content = Paragraph(f"<i>{invoice_footer}</i>", normal_style)
    
    # Right side: Signature
    if signature_obj and signature_obj.signature and signature_obj.signature.path:
        signature_path = signature_obj.signature.path
        if os.path.exists(signature_path):
            try:
                signature_img = Image(signature_path, width=40*mm, height=15*mm)
                sig_table = Table([[signature_img], [Paragraph("Authorized Signature", ParagraphStyle('sig', parent=normal_style, alignment=1))]], colWidths=[60*mm])
                sig_table.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
                right_content = sig_table
            except Exception:
                right_content = Paragraph("___________________<br/>Authorized Signature", ParagraphStyle('sig', parent=normal_style, alignment=1))
        else:
            right_content = Paragraph("___________________<br/>Authorized Signature", ParagraphStyle('sig', parent=normal_style, alignment=1))
    else:
        right_content = Paragraph("___________________<br/>Authorized Signature", ParagraphStyle('sig', parent=normal_style, alignment=1))
    
    footer_data.append([left_content, right_content])
    
    footer_table = Table(footer_data, colWidths=[250, 250])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
    ]))
    
    elements.append(footer_table)

    doc.build(elements)
    return response


# -------------------- SETTINGS VIEWS --------------------
@login_required
@user_passes_test(lambda u: u.is_superuser)
def company_settings(request):
    # Get or create settings
    settings_dict = {}
    signature_obj = None
    for setting in Settings.objects.all():
        settings_dict[setting.key] = setting.value
        if setting.key == 'signature':
            signature_obj = setting
    
    if request.method == 'POST':
        form = CompanySettingsForm(request.POST, request.FILES)
        if form.is_valid():
            # Update settings
            settings_fields = [
                'company_name', 'company_email', 'company_phone_1', 'company_phone_2',
                'company_address', 'invoice_prefix', 'invoice_footer'
            ]
            for field in settings_fields:
                value = form.cleaned_data.get(field, '')
                Settings.objects.update_or_create(
                    key=field,
                    defaults={'value': value}
                )
            
            # Handle signature upload
            if 'signature' in request.FILES and request.FILES['signature']:
                if signature_obj:
                    # Update existing signature
                    signature_obj.signature = request.FILES['signature']
                    signature_obj.save()
                else:
                    # Create new signature setting
                    Settings.objects.create(
                        key='signature',
                        value='',
                        signature=request.FILES['signature']
                    )
            elif signature_obj and not request.FILES.get('signature'):
                # If no new signature uploaded and we have an existing one, keep it
                pass
            
            from django.contrib import messages
            messages.success(request, 'Settings updated successfully!')
            return redirect('company_settings')
    else:
        initial_data = {
            'company_name': settings_dict.get('company_name', 'DOSTAUTOGARAGE'),
            'company_email': settings_dict.get('company_email', 'dostautogarage@gmail.com'),
            'company_phone_1': settings_dict.get('company_phone_1', '9746519367'),
            'company_phone_2': settings_dict.get('company_phone_2', '9745582281'),
            'company_address': settings_dict.get('company_address', ''),
            'invoice_prefix': settings_dict.get('invoice_prefix', 'KNJ'),
            'invoice_footer': settings_dict.get('invoice_footer', 'Thank you for your business!'),
        }
        form = CompanySettingsForm(initial=initial_data)
    
    return render(request, 'billing/company_settings.html', {
        'form': form,
        'settings': settings_dict,
        'signature_obj': signature_obj
    })


# -------------------- ADMIN MANAGEMENT --------------------
@login_required
@user_passes_test(lambda u: u.is_superuser)
def admin_list(request):
    """List all admin users"""
    query = request.GET.get('q', '').strip()
    User = get_user_model()
    admins = User.objects.filter(is_superuser=True).order_by('-date_joined')
    
    if query:
        admins = admins.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )
    
    per_page = int(request.GET.get('per_page', 100))
    if per_page not in [100, 200, 300, 500]:
        per_page = 100

    paginator = Paginator(admins, per_page)
    page_number = request.GET.get('page')
    admin_page = paginator.get_page(page_number)
    
    return render(request, 'billing/admin_list.html', {
        'admins': admin_page,
        'query': query,
        'per_page': per_page,
    })


@login_required
@user_passes_test(lambda u: u.is_superuser and u.pk == 1)
def admin_create(request):
    """Create a new admin user"""
    if request.method == 'POST':
        form = AdminCreationForm(request.POST)
        if form.is_valid():
            form.save()
            from django.contrib import messages
            messages.success(request, f'Admin user "{form.cleaned_data.get("username")}" created successfully!')
            return redirect('admin_list')
    else:
        form = AdminCreationForm()
    
    return render(request, 'billing/admin_form.html', {
        'form': form,
        'title': 'Create New Admin',
        'submit_text': 'Create Admin'
    })


@login_required
@user_passes_test(lambda u: u.is_superuser and u.pk == 1)
def admin_edit(request, pk):
    """Edit an admin user"""
    User = get_user_model()
    admin = get_object_or_404(User, pk=pk, is_superuser=True)
    
    if request.method == 'POST':
        form = AdminEditForm(request.POST, instance=admin)
        if form.is_valid():
            form.save()
            from django.contrib import messages
            messages.success(request, f'Admin user "{admin.username}" updated successfully!')
            return redirect('admin_list')
    else:
        form = AdminEditForm(instance=admin)
    
    return render(request, 'billing/admin_form.html', {
        'form': form,
        'admin': admin,
        'title': f'Edit Admin: {admin.username}',
        'submit_text': 'Update Admin'
    })


@login_required
@user_passes_test(lambda u: u.is_superuser and u.pk == 1)
def admin_delete(request, pk):
    """Delete an admin user"""
    User = get_user_model()
    admin = get_object_or_404(User, pk=pk, is_superuser=True)
    
    # Prevent deleting the current user
    if admin.pk == request.user.pk:
        from django.contrib import messages
        messages.error(request, 'You cannot delete your own admin account!')
        return redirect('admin_list')
    
    if request.method == 'POST':
        username = admin.username
        admin.delete()
        from django.contrib import messages
        messages.success(request, f'Admin user "{username}" deleted successfully!')
        return redirect('admin_list')
    
    return render(request, 'billing/admin_confirm_delete.html', {'admin': admin})

# -------------------- PWA SUPPORT --------------------
def manifest_json(request):
    manifest = {
        "name": "Dost Garage Settings",
        "short_name": "DostGarage",
        "start_url": "/dashboard/",
        "display": "standalone",
        "background_color": "#1e293b",
        "theme_color": "#1e293b",
        "icons": [
            {
                "src": "/static/logo.png",
                "sizes": "192x192 512x512",
                "type": "image/png"
            }
        ]
    }
    return JsonResponse(manifest)

def sw_js(request):
    sw_code = "self.addEventListener('fetch', function(event) { });"
    return HttpResponse(sw_code, content_type='application/javascript')