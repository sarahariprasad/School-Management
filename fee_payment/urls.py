"""
URL patterns for fee_payment app.
"""

from django.urls import path
from . import views

app_name = 'fee_payment'

urlpatterns = [
    # Fee Category
    path('categories/', views.FeeCategoryListView.as_view(), name='fee_category_list'),
    path('categories/add/', views.FeeCategoryCreateView.as_view(), name='fee_category_create'),
    path('categories/<int:pk>/edit/', views.FeeCategoryUpdateView.as_view(), name='fee_category_update'),
    path('categories/<int:pk>/delete/', views.FeeCategoryDeleteView.as_view(), name='fee_category_delete'),

    # Fee Structure
    path('structures/', views.FeeStructureListView.as_view(), name='fee_structure_list'),
    path('structures/add/', views.FeeStructureCreateView.as_view(), name='fee_structure_create'),
    path('structures/<int:pk>/edit/', views.FeeStructureUpdateView.as_view(), name='fee_structure_update'),
    path('structures/<int:pk>/delete/', views.FeeStructureDeleteView.as_view(), name='fee_structure_delete'),

    # Student Fee Assignment
    path('assignments/', views.StudentFeeAssignmentListView.as_view(), name='student_fee_assignment_list'),
    path('assignments/<int:pk>/', views.StudentFeeAssignmentDetailView.as_view(), name='student_fee_assignment_detail'),
    path('assignments/add/', views.StudentFeeAssignmentCreateView.as_view(), name='student_fee_assignment_create'),
    path('assignments/<int:pk>/edit/', views.StudentFeeAssignmentUpdateView.as_view(), name='student_fee_assignment_update'),
    path('assignments/<int:pk>/delete/', views.StudentFeeAssignmentDeleteView.as_view(), name='student_fee_assignment_delete'),

    # Fee Installment
    path('installments/', views.FeeInstallmentListView.as_view(), name='fee_installment_list'),
    path('installments/add/', views.FeeInstallmentCreateView.as_view(), name='fee_installment_create'),
    path('installments/<int:pk>/edit/', views.FeeInstallmentUpdateView.as_view(), name='fee_installment_update'),
    path('installments/<int:pk>/delete/', views.FeeInstallmentDeleteView.as_view(), name='fee_installment_delete'),

    # Fee Payment
    path('payments/', views.FeePaymentListView.as_view(), name='fee_payment_list'),
    path('payments/<int:pk>/', views.FeePaymentDetailView.as_view(), name='fee_payment_detail'),
    path('payments/add/', views.FeePaymentCreateView.as_view(), name='fee_payment_create'),
    path('payments/<int:pk>/edit/', views.FeePaymentUpdateView.as_view(), name='fee_payment_update'),
    path('payments/<int:pk>/delete/', views.FeePaymentDeleteView.as_view(), name='fee_payment_delete'),
    path('payments/<int:pk>/receipt/', views.FeePaymentReceiptView.as_view(), name='fee_payment_receipt'),

    # Bulk Reminders
    path('send-reminders/', views.SendDueRemindersView.as_view(), name='send_due_reminders'),

    # Reports (NEW)
    path('reports/daily-collection/', views.DailyCollectionReportView.as_view(), name='daily_collection_report'),
]