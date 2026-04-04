from django.urls import path
from . import views

urlpatterns = [
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.product_add, name='product_add'),
    path('products/<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),

    path('invoices/', views.invoice_list, name='invoice_list'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('invoices/add/', views.invoice_create, name='invoice_create'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/delete/', views.invoice_delete, name='invoice_delete'),
    path('invoices/<int:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('products/<int:pk>/add-stock/', views.product_add_stock, name='product_add_stock'),
    path('api/product-search/', views.product_search_api, name='product_search_api'),
    path('api/products/', views.product_list_api, name='product_list_api'),
    
    path('settings/', views.company_settings, name='company_settings'),
    
    # Admin Management
    path('admins/', views.admin_list, name='admin_list'),
    path('admins/create/', views.admin_create, name='admin_create'),
    path('admins/<int:pk>/edit/', views.admin_edit, name='admin_edit'),
    path('admins/<int:pk>/delete/', views.admin_delete, name='admin_delete'),
]