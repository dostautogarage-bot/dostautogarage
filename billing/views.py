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
import re
from django.utils import timezone

from .models import Product, Invoice, InvoiceItem, OtherCharge, Settings, Expense
from django.db import transaction

# ReportLab
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, KeepTogether
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from django.http import JsonResponse
import json


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
    created_at = forms.DateTimeField(
        required=True,
        label='Invoice Date',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d')
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.initial.get('created_at'):
            self.initial['created_at'] = timezone.now().strftime('%Y-%m-%d')
        elif self.instance.pk:
            self.initial['created_at'] = self.instance.created_at.strftime('%Y-%m-%d')
    
    class Meta:
        model = Invoice
        fields = [
            'created_at',
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
def product_export_pdf(request):
    products = Product.objects.all().order_by('name')

    font_normal = 'Helvetica'
    font_bold = 'Helvetica-Bold'
    try:
        if os.path.exists('C:/Windows/Fonts/segoeui.ttf'):
            pdfmetrics.registerFont(TTFont('SegoeUI', 'C:/Windows/Fonts/segoeui.ttf'))
            pdfmetrics.registerFont(TTFont('SegoeUI-Bold', 'C:/Windows/Fonts/segoeuib.ttf'))
            font_normal = 'SegoeUI'
            font_bold = 'SegoeUI-Bold'
    except Exception:
        pass

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="products.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontName=font_bold,
        fontSize=22,
        textColor=colors.HexColor('#0f172a'),
        spaceAfter=8
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontName=font_normal,
        fontSize=11,
        textColor=colors.HexColor('#475569'),
        spaceAfter=16
    )
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Heading2'],
        fontName=font_bold,
        fontSize=11,
        textColor=colors.HexColor('#0f172a')
    )
    normal_style = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontName=font_normal,
        fontSize=10,
        textColor=colors.HexColor('#334155')
    )

    elements = []
    elements.append(Paragraph('Product List', title_style))
    elements.append(Paragraph(f'Total products: {products.count()}', subtitle_style))
    elements.append(Spacer(1, 12))

    data = [[
        Paragraph('#', header_style),
        Paragraph('Name', header_style),
        Paragraph('Part Number', header_style),
        Paragraph('Price', header_style),
        Paragraph('Stock', header_style),
    ]]

    for index, product in enumerate(products, start=1):
        data.append([
            Paragraph(str(index), normal_style),
            Paragraph(product.name or '-', normal_style),
            Paragraph(product.part_number or '-', normal_style),
            Paragraph(f'₹ {product.price}', normal_style),
            Paragraph(str(product.stock), normal_style),
        ])

    table = Table(data, colWidths=[30, 200, 130, 80, 50], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('FONTNAME', (0, 0), (-1, 0), font_bold),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (3, 1), (4, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ffffff')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor('#94a3b8')),
    ]))

    elements.append(table)
    doc.build(elements)
    return response


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

    show_drafts = request.GET.get('drafts') == '1'

    if show_drafts:
        invoices = Invoice.objects.filter(status='DRAFT').order_by('-invoice_number').select_related('created_by').prefetch_related('items', 'other_charges')
    else:
        invoices = Invoice.objects.filter(status='COMPLETED').order_by('-invoice_number').select_related('created_by').prefetch_related('items', 'other_charges')
    
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

    # ABSOLUTE FAILSAFE: Force python-level sort descending
    invoices_list = list(invoices)
    invoices_list.sort(key=lambda x: x.invoice_number, reverse=True)

    # Assign color index based on creator ID
    for inv in invoices_list:
        inv.color_index = (inv.created_by.id % 6) if inv.created_by else 0

    paginator = Paginator(invoices_list, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    draft_count = Invoice.objects.filter(status='DRAFT').count()

    return render(request, 'billing/invoice_list.html', {
        'invoices': page_obj,
        'query': query,
        'per_page': per_page,
        'users': users,
        'selected_creator': creator_id,
        'start_date': start_date,
        'end_date': end_date,
        'show_drafts': show_drafts,
        'draft_count': draft_count,
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
        created_at__date__lte=end,
        status='COMPLETED'
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
    
    # Differentiate Labour and Other Charges
    all_other_charges_qs = OtherCharge.objects.filter(invoice__in=invoices)
    total_labour_charges = all_other_charges_qs.filter(Q(name__icontains='LABOUR') | Q(name__icontains='LABOR')).aggregate(total=Sum('amount'))['total'] or 0
    total_other_charges_only = all_other_charges_qs.exclude(Q(name__icontains='LABOUR') | Q(name__icontains='LABOR')).aggregate(total=Sum('amount'))['total'] or 0
    total_other_charges = total_labour_charges + total_other_charges_only
    total_discount = invoices.aggregate(total_discount=Sum('discount_amount'))['total_discount'] or 0
    balance_amount = total_invoice_value - total_discount
    total_expenses = Expense.objects.filter(date__gte=start, date__lte=end).aggregate(total_amount=Sum('amount'))['total_amount'] or Decimal('0')

    if admin_invoices is not None:
        admin_invoice_count = admin_invoices.count()
        admin_products_sold = InvoiceItem.objects.filter(invoice__in=admin_invoices).aggregate(total_qty=Sum('quantity'))['total_qty'] or 0
        
        # Admin-specific Labour vs Other
        admin_other_qs = OtherCharge.objects.filter(invoice__in=admin_invoices)
        admin_labour = admin_other_qs.filter(Q(name__icontains='LABOUR') | Q(name__icontains='LABOR')).aggregate(total=Sum('amount'))['total'] or 0
        admin_other_only = admin_other_qs.exclude(Q(name__icontains='LABOUR') | Q(name__icontains='LABOR')).aggregate(total=Sum('amount'))['total'] or 0
        
        admin_total_discount = admin_invoices.aggregate(total_discount=Sum('discount_amount'))['total_discount'] or 0
        admin_balance_amount = sum(invoice.grand_total for invoice in admin_invoices) - admin_total_discount
        admin_expenses = Expense.objects.filter(created_by=admin_user, date__gte=start, date__lte=end).aggregate(total_amount=Sum('amount'))['total_amount'] or Decimal('0')
        admin_stats = {
            'invoice_count': admin_invoice_count,
            'products_sold': admin_products_sold,
            'labour_charges': admin_labour,
            'other_charges_only': admin_other_only,
            'total_discount': admin_total_discount,
            'balance_amount': admin_balance_amount,
            'expenses': admin_expenses,
        }
    else:
        admin_stats = None

    user_counts = invoices.values(
        'created_by__id',
        'created_by__username',
        'created_by__first_name',
        'created_by__last_name'
    ).annotate(count=Count('pk')).order_by('-count')

    user_chart_labels = []
    user_chart_values = []
    user_chart_ids    = []
    for row in user_counts:
        # Assign color index for table rows
        row['color_index'] = (row['created_by__id'] % 6) if row['created_by__id'] else 0

        username = row['created_by__username'] or 'Unknown'
        full_name = (row['created_by__first_name'] or row['created_by__last_name'] or '').strip()
        label = full_name or username
        user_chart_labels.append(label)
        user_chart_values.append(row['count'])
        user_chart_ids.append(row['created_by__id'] or 0)

    top_products = InvoiceItem.objects.filter(invoice__in=invoices).values('product__name').annotate(total_qty=Sum('quantity')).order_by('-total_qty')[:5]

    return render(request, 'billing/dashboard.html', {
        'start_date': start.strftime('%Y-%m-%d'),
        'end_date': end.strftime('%Y-%m-%d'),
        'invoice_count': invoice_count,
        'month': month,
        'total_invoice_value': total_invoice_value,
        'products_sold': products_sold,
        'total_labour_charges': total_labour_charges,
        'total_other_charges_only': total_other_charges_only,
        'total_other_charges': total_other_charges,
        'total_discount': total_discount,
        'balance_amount': balance_amount,
        'user_counts': user_counts,
        'user_chart_labels': user_chart_labels,
        'user_chart_values': user_chart_values,
        'user_chart_ids': user_chart_ids,
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

# ─── Utility for Form Errors ─────────────────────────────────────────────
def get_form_errors(form, formset=None):
    errors = {}
    if form:
        for field, error_list in form.errors.items():
            errors[field] = error_list[0] if error_list else ""
    if formset:
        formset_errors = []
        for f in formset:
            f_errors = {}
            for field, error_list in f.errors.items():
                f_errors[field] = error_list[0] if error_list else ""
            formset_errors.append(f_errors)
        errors['formset'] = formset_errors
    return errors

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
                msg = "Please add at least one product or one charge."
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'message': msg}, status=400)
                messages.error(request, msg)
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
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'errors': get_form_errors(main_form, formset)}, status=400)
                return render(request, 'billing/invoice_form.html', {
                    'formset'  : formset,
                    'main_form': main_form,
                    'products' : Product.objects.all()
                })

            try:
                with transaction.atomic():
                    # ── Invoice number ───────────────────────────────────────────────
                    last_invoice = Invoice.objects.select_for_update().order_by('-invoice_number').first()
                    next_number  = (last_invoice.invoice_number if last_invoice else 0) + 1

                    is_draft = 'save_draft' in request.POST

                    invoice = main_form.save(commit=False)
                    invoice.invoice_number = next_number
                    invoice.created_by = request.user
                    invoice.discount_amount = main_form.cleaned_data.get('discount_amount') or 0
                    invoice.status = 'DRAFT' if is_draft else 'COMPLETED'
                    invoice.save()

                    # ── Invoice items ────────────────────────────────────────────────
                    for form in formset:
                        if not form.cleaned_data:
                            continue

                        product  = form.cleaned_data.get('product')
                        quantity = form.cleaned_data.get('quantity')

                        if not product or not quantity:
                            continue
                        
                        # Lock product for update
                        p_locked = Product.objects.select_for_update().get(pk=product.pk)

                        if not is_draft and p_locked.stock < quantity:
                            available = p_locked.stock.quantize(Decimal('0.01')).normalize() if isinstance(p_locked.stock, Decimal) else p_locked.stock
                            err_msg = f'Only {available} available for {product.name}'
                            form.add_error('quantity', err_msg)
                            raise Exception(err_msg)

                        InvoiceItem.objects.create(
                            invoice  = invoice,
                            product  = product,
                            quantity = quantity,
                            price    = product.price
                        )

                        if not is_draft:
                            p_locked.stock -= quantity
                            p_locked.save()

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
                        pass

                    messages.success(request, f'Invoice #{invoice.formatted_invoice_number} created successfully.')
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'success', 'redirect': f"/invoices/{invoice.pk}/"})
                    return redirect('invoice_detail', pk=invoice.pk)

            except Exception as e:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'errors': get_form_errors(main_form, formset)}, status=400)
                
                return render(request, 'billing/invoice_form.html', {
                    'formset'  : formset,
                    'main_form': main_form,
                    'products' : Product.objects.all()
                })

    # If forms were invalid (non-AJAX)
    if request.method == 'POST':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'errors': get_form_errors(main_form, formset)}, status=400)

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
        with transaction.atomic():
            # Restore stock if invoice was COMPLETED
            if invoice.status == 'COMPLETED':
                for item in invoice.items.all():
                    item.product.stock += item.quantity
                    item.product.save()
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
    formset = ItemFormSet(
        request.POST or None,
        initial=[
            {
                'product': item.product.pk if item.product else None,
                'quantity': item.quantity,
                'product_name': item.product.name if item.product else f'[DELETED PRODUCT - ID: {item.product_id}]',
                'price': item.price,
            }
            for item in invoice.items.all()
        ]
    )
    main_form = InvoiceMainForm(request.POST or None, instance=invoice)
    other_charges = list(invoice.other_charges.all())

    if request.method == 'POST':
        charges_raw = request.POST.get('other_charges', '[]')
        try:
            total_charges_posted = len(json.loads(charges_raw))
        except:
            total_charges_posted = 0

        if formset.is_valid() and main_form.is_valid():
            try:
                with transaction.atomic():
                    total_items_posted = sum(1 for f in formset if f.cleaned_data and not f.cleaned_data.get('DELETE', False) and f.cleaned_data.get('product'))

                    if total_items_posted == 0 and total_charges_posted == 0:
                        msg = "Please add at least one product or one charge."
                        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                            return JsonResponse({'status': 'error', 'message': msg}, status=400)
                        messages.error(request, msg)
                        return render(request, 'billing/invoice_form.html', {'formset': formset, 'main_form': main_form, 'products': Product.objects.all(), 'editing': True, 'invoice': invoice, 'other_charges': other_charges})

                    # ... (rest of validation) ...
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
                        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                            return JsonResponse({'status': 'error', 'errors': get_form_errors(main_form, formset)}, status=400)
                        return render(request, 'billing/invoice_form.html', {'formset': formset, 'main_form': main_form, 'products': Product.objects.all(), 'editing': True, 'invoice': invoice, 'other_charges': other_charges})

                    is_draft = 'save_draft' in request.POST
                    was_draft = invoice.status == 'DRAFT'

                    # Update main invoice
                    invoice = main_form.save(commit=False)
                    invoice.status = 'DRAFT' if is_draft else 'COMPLETED'
                    invoice.save()

                    # Gather old quantities
                    old_quantities = {}
                    if not was_draft:
                        for item in invoice.items.all():
                            old_quantities[item.product_id] = old_quantities.get(item.product_id, Decimal('0')) + item.quantity

                    new_items = []
                    for form in formset:
                        if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                            product = form.cleaned_data.get('product')
                            quantity = form.cleaned_data.get('quantity')
                            if product and quantity > 0:
                                new_items.append((form, product, quantity))

                    # Validate stock without changing it yet
                    if not is_draft:
                        for form, product, quantity in new_items:
                            # Lock the product for update
                            p_locked = Product.objects.select_for_update().get(pk=product.pk)
                            old_quantity = old_quantities.get(product.pk, Decimal('0'))
                            delta = Decimal(quantity) - old_quantity
                            if delta > 0 and p_locked.stock < delta:
                                available = p_locked.stock.quantize(Decimal('0.01')).normalize() if isinstance(p_locked.stock, Decimal) else p_locked.stock
                                err_msg = f'Only {available} available for {product.name}'
                                form.add_error('quantity', err_msg)
                                raise Exception(err_msg)

                    # Apply stock changes: First refund old quantities
                    for product_id, old_quantity in old_quantities.items():
                        product = Product.objects.select_for_update().get(pk=product_id)
                        product.stock += old_quantity
                        product.save()

                    invoice.items.all().delete()  # Clear existing items

                    # Save updated items and apply new stock deductions if not a draft
                    for form, product, quantity in new_items:
                        if not is_draft:
                            p_to_deduct = Product.objects.select_for_update().get(pk=product.pk)
                            p_to_deduct.stock -= Decimal(quantity)
                            p_to_deduct.save()
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
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({'status': 'success', 'redirect': f"/invoices/{invoice.pk}/"})
                    return redirect('invoice_detail', pk=invoice.pk)
            
            except Exception as e:
                # If it was a stock error we raised or something else
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'error', 'errors': get_form_errors(main_form, formset)}, status=400)
                return render(request, 'billing/invoice_form.html', {
                    'formset': formset,
                    'main_form': main_form,
                    'products': Product.objects.all(),
                    'editing': True,
                    'invoice': invoice,
                    'other_charges': other_charges
                })

    # If forms were invalid (non-AJAX)
    if request.method == 'POST':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'errors': get_form_errors(main_form, formset)}, status=400)

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


@login_required
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

    # Aggressive margin reduction to fit more content
    doc = SimpleDocTemplate(
        response, 
        pagesize=A4, 
        rightMargin=20, 
        leftMargin=20, 
        topMargin=18, 
        bottomMargin=18
    )

    elements = []
    
    # Custom styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'MainTitle',
        parent=styles['Heading1'],
        fontName=font_bold,
        fontSize=16,
        textColor=colors.HexColor("#1e293b"),
        alignment=0
    )
    company_name_style = ParagraphStyle(
        'CompName',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#2563eb"),
        alignment=2
    )
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontName=font_normal,
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#475569")
    )
    bold_style = ParagraphStyle(
        'CustomBold',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=7.5,
        textColor=colors.HexColor("#1e293b")
    )

    # ─── Resolve Settings & Context ──────────────────
    from .models import Settings
    settings_dict = {}
    for s in Settings.objects.all():
        settings_dict[s.key] = s.value

    company_name    = settings_dict.get('company_name', 'DOST AUTO GARAGE')
    company_address = settings_dict.get('company_address', 'Address not set')
    company_email   = settings_dict.get('company_email', '')
    company_phone_1 = settings_dict.get('company_phone_1', '')
    company_phone_2 = settings_dict.get('company_phone_2', '')
    invoice_footer  = settings_dict.get('invoice_footer', 'Thank you for your business!')
    currency_symbol = settings_dict.get('currency_symbol', 'INR')

    phone_text = company_phone_1
    if company_phone_2:
        phone_text = f"{company_phone_1}, {company_phone_2}"

    logo_obj = Settings.objects.filter(key='company_logo').first()
    signature_obj = Settings.objects.filter(key='signature').first()

    # ──────────────── HEADER ────────────────
    # Fetch Logo if available
    logo_path = None
    if logo_obj:
        if logo_obj.signature and os.path.exists(logo_obj.signature.path):
            logo_path = logo_obj.signature.path
        elif logo_obj.value and os.path.exists(logo_obj.value):
            logo_path = logo_obj.value

    # Left Header: Invoice Main Info
    left_header = [
        Paragraph("INVOICE", title_style),
        Spacer(1, 2),
        Paragraph(f"<b>Invoice #:</b> {invoice_number}", bold_style),
        Paragraph(f"<b>Date:</b> {invoice.created_at.strftime('%d %b %Y')}", normal_style)
    ]
    
    # Right Header: Company branding and info
    right_header = []
    if logo_path:
        try:
            logo = Image(logo_path, width=22*mm, height=10*mm)
            logo.hAlign = 'RIGHT'
            right_header.append(logo)
            right_header.append(Spacer(1, 2))
        except:
            pass

    right_header.append(Paragraph(f"<b>{company_name}</b>", company_name_style))
    right_header.append(Spacer(1, 8)) # Significant space to prevent overlap
    right_header.append(Paragraph(company_address, ParagraphStyle('comp_addr', parent=normal_style, alignment=2)))
    if company_email:
        right_header.append(Paragraph(f"Email: {company_email}", ParagraphStyle('comp_email', parent=normal_style, alignment=2)))
    right_header.append(Paragraph(f"Phone: {phone_text}", ParagraphStyle('comp_phone', parent=normal_style, alignment=2)))

    header_table = Table([[left_header, right_header]], colWidths=[200, 300])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(header_table)

    from reportlab.platypus import HRFlowable
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceBefore=2, spaceAfter=2))
    
    # ──────────────── CUSTOMER & SERVICE INFO ────────────────
    created_by_name = invoice.created_by.get_full_name() or invoice.created_by.username if invoice.created_by else "System"
    
    # Left Block: Customer
    cust_data = f"<b>BILL TO:</b><br/>"
    cust_data += f"<b>{invoice.customer_name.upper() if invoice.customer_name else 'N/A'}</b><br/>"
    cust_data += f"Phone: {invoice.customer_phone or 'N/A'}"
    
    # Right Block: Service Info
    serv_data = f"<b>SERVICE DETAILS:</b><br/>"
    serv_data += f"Vehicle: <b>{invoice.vehicle_number.upper() if invoice.vehicle_number else 'N/A'}</b><br/>"
    if invoice.mechanic_name:
        serv_data += f"Mechanic: {invoice.mechanic_name.upper()}<br/>"
    if invoice.ran_kilometer:
        serv_data += f"Service: {invoice.ran_kilometer} KM<br/>"
    serv_data += f"Prepared by: {created_by_name.title()}"

    cv_table = Table([[Paragraph(cust_data, normal_style), Paragraph(serv_data, normal_style)]], colWidths=[240, 260])
    cv_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(cv_table)
    elements.append(Spacer(1, 4))

    # ---------------- PRODUCT TABLE ----------------
    data = [["DESCRIPTION", "QTY", "RATE", "AMOUNT"]]
    for item in invoice.items.all():
        data.append([
            item.product.name.upper(),
            str(item.quantity),
            f"{item.price:.2f}",
            f"{item.total_price:.2f}"
        ])
    
    # Append Product Subtotal
    data.append(["", "", "Product Subtotal:", f"{invoice.total:.2f}"])

    product_table = Table(data, colWidths=[240, 60, 100, 100])
    product_table.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0), colors.HexColor("#1e293b")),
        ('TEXTCOLOR',     (0,0), (-1,0), colors.white),
        ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,0), 8),
        ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE',      (0,1), (-1,-1), 7.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING',    (0,0), (-1,-1), 2),
        ('ALIGN',         (1,0), (-1,-1), 'CENTER'),
        ('ALIGN',         (3,0), (-1,-1), 'RIGHT'),
        ('LINEBELOW',     (0,0), (-1,-2), 0.5, colors.HexColor("#e2e8f0")),
        # Style for the subtotal row
        ('FONTNAME',      (2,-1), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN',         (2,-1), (2,-1), 'RIGHT'),
        ('LINEABOVE',     (2,-1), (-1,-1), 1, colors.HexColor("#cbd5e1")),
    ]))
    elements.append(product_table)
    elements.append(Spacer(1, 5))

    # ──────────────── OTHER CHARGES ────────────────
    if invoice.other_charges.exists():
        # Wrap heading in a table to ensure margin alignment matches other tables (500 width)
        heading_table = Table([[Paragraph("<b>OTHER CHARGES</b>", normal_style)]], colWidths=[500])
        heading_table.setStyle(TableStyle([('LEFTPADDING', (0,0), (-1,-1), 0), ('BOTTOMPADDING', (0,0), (-1,-1), 2)]))
        elements.append(heading_table)
        
        other_data = [["CHARGE", "AMOUNT"]]
        for charge in invoice.other_charges.all():
            other_data.append([charge.name.upper(), f"{charge.amount:.2f}"])
        
        # Append Other Charges Subtotal
        other_data.append(["Charges Subtotal:", f"{invoice.other_charges_total:.2f}"])
        
        other_table = Table(other_data, colWidths=[400, 100])
        other_table.setStyle(TableStyle([
            ('FONTNAME',      (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',      (0,0), (-1,0), 8),
            ('FONTNAME',      (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE',      (0,1), (-1,-1), 7.5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1.5),
            ('TOPPADDING',    (0,0), (-1,-1), 1.5),
            ('ALIGN',         (1,0), (-1,-1), 'RIGHT'),
            ('GRID',          (0,0), (-1,-2), 0.5, colors.HexColor("#f1f5f9")),
            # Style for the subtotal row
            ('FONTNAME',      (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('ALIGN',         (0,-1), (0,-1), 'RIGHT'),
            ('LINEABOVE',     (0,-1), (-1,-1), 1, colors.HexColor("#cbd5e1")),
        ]))
        elements.append(other_table)
        elements.append(Spacer(1, 4))

    # ---------------- TOTALS ----------------
    disc_val  = invoice.discount_amount or 0
    bal_val   = invoice.balance_amount

    totals_data = []
    totals_data.append(["Gross Total:", f"{currency_symbol} {invoice.grand_total:.2f}"])
    if disc_val > 0:
        totals_data.append(["Discount:", f"- {currency_symbol} {disc_val:.2f}"])
    totals_data.append(["GRAND TOTAL:", f"{currency_symbol} {bal_val:.2f}"])
    
    totals_table = Table(totals_data, colWidths=[350, 150])
    totals_table.setStyle(TableStyle([
        ('FONTNAME',   (0,0),  (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,0),  (-1,-1), 8),
        ('ALIGN',      (1,0),  (1,-1), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING',    (0,0), (-1,-1), 2),
        ('FONTNAME',   (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,-1), (-1,-1), 9.5),
        ('LINEABOVE',  (0,-1), (-1,-1), 1, colors.HexColor("#e2e8f0")),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 6))

    # ──────────────── FOOTER ────────────────
    clean_footer = re.sub(r'<a[^>]*>.*?</a>', '', invoice_footer, flags=re.IGNORECASE | re.DOTALL)
    left_content = Paragraph(f"<i>{clean_footer}</i>", normal_style)
    
    sig_path = None
    if signature_obj:
        if signature_obj.signature and os.path.exists(signature_obj.signature.path):
            sig_path = signature_obj.signature.path
        elif signature_obj.value and os.path.exists(signature_obj.value):
            sig_path = signature_obj.value

    if sig_path:
        try:
            signature_img = Image(sig_path, width=30*mm, height=10*mm)
            right_content = Table([[signature_img], [Paragraph("Authorized Signature", ParagraphStyle('sig', parent=normal_style, alignment=1))]], colWidths=[40*mm])
            right_content.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        except Exception as e:
            print(f"Signature error: {e}")
            right_content = Paragraph("___________________<br/>Authorized Signature", ParagraphStyle('sig', parent=normal_style, alignment=1))
    else:
        right_content = Paragraph("___________________<br/>Authorized Signature", ParagraphStyle('sig', parent=normal_style, alignment=1))
    
    footer_data = [[left_content, right_content]]
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