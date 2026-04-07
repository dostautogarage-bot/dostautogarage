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

from .models import Product, Invoice, InvoiceItem, OtherCharge, Settings, Expense

# ReportLab
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, KeepTogether
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet


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
    discount_amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    next_due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    ran_kilometer = forms.IntegerField(
        required=False,
        label='Next Service Kilometer',
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = Invoice
        fields = [
            'customer_name',
            'customer_phone',
            'vehicle_number',
            'discount_amount',
            'next_due_date',
            'ran_kilometer'
        ]
        widgets = {
            'customer_name': forms.TextInput(attrs={'class': 'form-control'}),
            'customer_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'vehicle_number': forms.TextInput(attrs={'class': 'form-control'}),
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
    return render(request, 'billing/product_list.html', {
        'products': products,
        'total_product_worth': total_product_worth
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

    return render(request, 'billing/expense_list.html', {
        'expenses': expenses,
        'form': form,
        'users': users,
        'selected_admin': admin_filter,
        'total_expenses': total_expenses,
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
    per_page = int(request.GET.get('per_page', 10))

    invoices = Invoice.objects.all().order_by('-created_at')
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

    invoices = Invoice.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
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
        min_num=1,
        validate_min=True,
        can_delete=False
    )

    formset   = ItemFormSet(request.POST or None)
    main_form = InvoiceMainForm(request.POST or None)

    if request.method == 'POST':
        if formset.is_valid() and main_form.is_valid():
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
                    form.add_error('quantity', f'Not enough stock for {product.name}')
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
        'products' : Product.objects.filter(stock__gt=0)  # only in-stock for dropdown
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
        min_num=1,
        validate_min=True,
        can_delete=True
    )
    formset = ItemFormSet(request.POST or None, initial=[{'product': item.product.pk, 'quantity': item.quantity} for item in invoice.items.all()])
    main_form = InvoiceMainForm(request.POST or None, instance=invoice)
    other_charges = list(invoice.other_charges.all())

    if request.method == 'POST' and formset.is_valid() and main_form.is_valid():
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

        # Handle invoice items - restore stock for existing items, then recreate
        for item in invoice.items.all():
            item.product.stock += item.quantity  # Restore stock
            item.product.save()
        invoice.items.all().delete()  # Clear existing items
        
        for form in formset:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                product = form.cleaned_data.get('product')
                quantity = form.cleaned_data.get('quantity')
                if product and quantity > 0:
                    if product.stock >= quantity:
                        InvoiceItem.objects.create(invoice=invoice, product=product, quantity=quantity, price=product.price)
                        product.stock -= quantity
                        product.save()
                    else:
                        # Restore stock for previously processed items
                        for prev_item in invoice.items.all():
                            prev_item.product.stock -= prev_item.quantity
                            prev_item.product.save()
                        form.add_error('quantity', f'Not enough stock for {product.name}')
                        return render(request, 'billing/invoice_form.html', {'formset': formset, 'main_form': main_form, 'products': Product.objects.all(), 'editing': True, 'invoice': invoice, 'other_charges': other_charges})

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
    GET /api/products/?q=oil&page=1&per_page=25
    Used only by the product list page for live search + pagination.
    Delete and Add Stock still use normal form POST — no changes needed there.
    """
    query    = request.GET.get('q', '').strip()
    page     = max(1, int(request.GET.get('page', 1)))
    per_page = min(int(request.GET.get('per_page', 10)), 200)  # cap at 200

    qs = Product.objects.all().order_by('name')

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


@login_required
@user_passes_test(lambda u: u.is_superuser)
def invoice_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    invoice_number = invoice.formatted_invoice_number

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{invoice_number}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=20,
        bottomMargin=20
    )

    elements = []
    styles = getSampleStyleSheet()

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
    
    # Also try to get signature directly
    try:
        signature_obj = Settings.objects.get(key='signature')
    except Settings.DoesNotExist:
        signature_obj = None
    
    company_name = settings_dict.get('company_name', 'DOSTAUTOGARAGE')
    company_email = settings_dict.get('company_email', 'dostautogarage@gmail.com')
    company_phone_1 = settings_dict.get('company_phone_1', '9746519367')
    company_phone_2 = settings_dict.get('company_phone_2', '9745582281')
    company_address = settings_dict.get('company_address', '')
    invoice_footer = settings_dict.get('invoice_footer', 'Thank you for your business!')

    # Add phone 2 if it exists
    phone_text = company_phone_1
    if company_phone_2:
        phone_text = f"{company_phone_1}, {company_phone_2}"

    # ---------------- HEADER ----------------
    logo_path = os.path.join(settings.BASE_DIR, 'static/logo.png')

    header_data = []
    header_text = f"<b><font size=18 color='#FF9A00'>{company_name}</font></b><br/><font size=10>Email: {company_email} | Phone: {phone_text}</font>"
    if company_address:
        header_text += f"<br/><font size=9>{company_address}</font>"
    
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=40*mm, height=20*mm)
        header_data.append([logo, Paragraph(header_text, styles['Normal'])])
    else:
        header_data.append(["", Paragraph(header_text, styles['Normal'])])

    header_table = Table(header_data, colWidths=[80, 380])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (0,-1), 0),
        ('RIGHTPADDING', (0,0), (0,-1), 10),
        ('ALIGN', (1,0), (1,-1), 'LEFT')
    ]))

    elements.append(header_table)
    elements.append(Spacer(1, 15))

    # ---------------- INVOICE TITLE ----------------
    elements.append(Paragraph("<b><font size=14>INVOICE</font></b>", styles['Title']))
    elements.append(Spacer(1, 10))

    # ---------------- CUSTOMER INFO ----------------
    created_by_name = "-"
    if invoice.created_by:
        created_by_name = invoice.created_by.get_full_name() or invoice.created_by.username

    info_data = [
        ["Invoice No:", invoice_number,          "Date:",    invoice.created_at.strftime("%d-%m-%Y")],
        ["Customer:",  invoice.customer_name.upper() if invoice.customer_name else "",    "Phone:",   invoice.customer_phone],
        ["Vehicle Number:",   invoice.vehicle_number.upper() if invoice.vehicle_number else "-", "KM:", invoice.ran_kilometer or "-"],
        ["Prepared by:", created_by_name.upper(), "", ""]
    ]

    info_table = Table(info_data, colWidths=[90, 150, 70, 120])
    info_table.setStyle(TableStyle([
        ('FONTNAME',      (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',      (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))

    elements.append(info_table)
    elements.append(Spacer(1, 20))

    # ---------------- PRODUCT TABLE ----------------
    data = [["Product / Service", "Qty", "Rate", "Amount"]]

    for item in invoice.items.all():
        data.append([
            item.product.name.upper(),
            item.quantity,
            f"{currency_symbol} {item.price:.2f}",
            f"{currency_symbol} {item.total_price:.2f}"
        ])

    product_table = Table(data, colWidths=[240, 60, 80, 80])
    product_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0), colors.HexColor("#2E86C1")),
        ('TEXTCOLOR',     (0,0), (-1,0), colors.white),
        ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
        ('ALIGN',         (1,0), (-1,-1), 'CENTER'),
        ('LINEBELOW',     (0,0), (-1,0),  1, colors.black),
        ('LINEBELOW',     (0,-1), (-1,-1), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,0),  8),
        ('TOPPADDING',    (0,1), (-1,-1), 6),
    ]))

    elements.append(product_table)
    elements.append(Spacer(1, 10))

    # ---------------- SUBTOTAL ROW ----------------
    subtotal_data = [
        ["", "", "Products Total", f"{currency_symbol} {total:.2f}"]
    ]
    subtotal_table = Table(subtotal_data, colWidths=[240, 60, 80, 80])
    subtotal_table.setStyle(TableStyle([
        ('FONTNAME',  (0,0), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN',     (2,0), (-1,-1), 'CENTER'),
        ('TEXTCOLOR', (2,0), (-1,-1), colors.HexColor("#2E86C1")),
    ]))
    elements.append(subtotal_table)
    elements.append(Spacer(1, 16))

    # ---------------- OTHER CHARGES TABLE ----------------
    other_charges = invoice.other_charges.all()
    if other_charges.exists():
        charges_heading_data = [[Paragraph('<b>Other Charges</b>', styles['Heading4'])]]
        charges_heading_table = Table(charges_heading_data, colWidths=[460])
        charges_heading_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 11),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(charges_heading_table)
        elements.append(Spacer(1, 6))

        charges_data = [["Charge", "Amount"]]
        for charge in other_charges:
            charges_data.append([
                charge.name.upper(),
                f"{currency_symbol} {charge.amount:.2f}"
            ])
        charges_table = Table(charges_data, colWidths=[340, 120])
        charges_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0), colors.HexColor("#117A65")),
            ('TEXTCOLOR',     (0,0), (-1,0), colors.white),
            ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
            ('ALIGN',         (1,0), (-1,-1), 'CENTER'),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ('RIGHTPADDING',  (0,0), (-1,-1), 8),
            ('LINEBELOW',     (0,0), (-1,0),  1, colors.black),
            ('LINEBELOW',     (0,-1), (-1,-1), 1, colors.black),
            ('BOTTOMPADDING', (0,0), (-1,0),  8),
            ('TOPPADDING',    (0,1), (-1,-1), 6),
        ]))

        elements.append(charges_table)
        elements.append(Spacer(1, 10))

        # Charges subtotal
        charges_subtotal_data = [
            ["", "Charges Total", f"{currency_symbol} {other_charges_total:.2f}"]
        ]
        charges_subtotal_table = Table(charges_subtotal_data, colWidths=[300, 120, 80])
        charges_subtotal_table.setStyle(TableStyle([
            ('FONTNAME',  (0,0), (-1,-1), 'Helvetica-Bold'),
            ('ALIGN',     (1,0), (1,-1), 'LEFT'),
            ('ALIGN',     (2,0), (-1,-1), 'RIGHT'),
            ('TEXTCOLOR', (1,0), (-1,-1), colors.HexColor("#117A65")),
        ]))
        elements.append(charges_subtotal_table)
        elements.append(Spacer(1, 16))

    # ---------------- TOTALS (RIGHT SIDE) ----------------
    totals_data = [
        ["Products Total", f"{currency_symbol} {total:.2f}"]
    ]

    if other_charges.exists():
        totals_data.append(["Other Charges", f"{currency_symbol} {other_charges_total:.2f}"])

    totals_data += [
        ["Grand Total",    f"{currency_symbol} {grand_total:.2f}"],
        ["Discount",       f"{currency_symbol} {discount:.2f}"],
        ["Final Total",    f"{currency_symbol} {balance:.2f}"],
    ]

    totals_table = Table(totals_data, colWidths=[100, 100], hAlign='RIGHT')
    totals_table.setStyle(TableStyle([
        ('GRID',       (0,0),  (-1,-1), 0.5, colors.black),
        ('FONTNAME',   (0,0),  (-1,-1), 'Helvetica-Bold'),
        ('BACKGROUND', (0,0),  (-1,0),  colors.lightgrey),
        ('ALIGN',      (1,0),  (-1,-1), 'RIGHT'),

        # Highlight Grand Total row
        ('BACKGROUND', (0, 2 if other_charges.exists() else 1),
                       (-1, 2 if other_charges.exists() else 1),
                       colors.HexColor("#D6EAF8")),

        # Highlight Balance row (last row)
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#FADBD8")),
        ('TEXTCOLOR',  (0,-1), (-1,-1), colors.HexColor("#C0392B")),
    ]))

    elements.append(totals_table)
    elements.append(Spacer(1, 30))

    # ---------------- NEXT DUE DATE (CONDITIONAL) ----------------
    if invoice.next_due_date:
        next_due_text = f"NEXT SERVICE DUE: {invoice.next_due_date.strftime('%d-%m-%Y')}"
        if invoice.ran_kilometer:
            next_due_text += f" (BEFORE {invoice.ran_kilometer} KM)"
        
        next_due_paragraph = Paragraph(
            f"<b><font size=10 color='#E74C3C'>{next_due_text}</font></b>", 
            styles['Normal']
        )

        next_due_table = Table([[next_due_paragraph]], colWidths=[460], hAlign='LEFT')
        next_due_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#fdecea')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#E74C3C')),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))

        elements.append(next_due_table)
        elements.append(Spacer(1, 15))

    # ---------------- FOOTER ----------------
    # Create a table for proper alignment of footer text and signature
    footer_data = []
    
    # Left side: Thank you message
    left_content = Paragraph(f"<i>{invoice_footer}</i>", styles['Normal'])
    
    # Right side: Signature
    if signature_obj and signature_obj.signature and signature_obj.signature.path:
        # If signature image exists, include it
        signature_path = signature_obj.signature.path
        if os.path.exists(signature_path):
            try:
                signature_img = Image(signature_path, width=60*mm, height=25*mm)
                # Create a small table for signature image and text
                sig_table_data = [[signature_img], [Paragraph("<font size=8>Authorized Signature</font>", styles['Normal'])]]
                sig_table = Table(sig_table_data, colWidths=[60*mm])
                sig_table.setStyle(TableStyle([
                    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ]))
                right_content = sig_table
            except Exception as e:
                # If image loading fails, use text signature
                right_content = Paragraph("__________________________<br/><font size=8>Authorized Signature</font>", styles['Normal'])
        else:
            right_content = Paragraph("__________________________<br/><font size=8>Authorized Signature</font>", styles['Normal'])
    else:
        right_content = Paragraph("__________________________<br/><font size=8>Authorized Signature</font>", styles['Normal'])
    
    footer_data.append([left_content, right_content])
    
    footer_table = Table(footer_data, colWidths=[250, 250])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'CENTER'),
    ]))
    
    elements.append(footer_table)

    # ---------------- BUILD ----------------

    # ---------------- BUILD ----------------
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