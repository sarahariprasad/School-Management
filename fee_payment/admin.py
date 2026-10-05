from django.contrib import admin
from .models import (
    FeeCategory, FeeStructure, StudentFeeAssignment, FeeInstallment,
    FeePayment, AdditionalCharge,
)


@admin.register(FeeCategory)
class FeeCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'description']
    list_filter = ['is_active']
    search_fields = ['name']


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ['branch', 'group', 'category', 'academic_year', 'amount', 'is_active']
    list_filter = ['branch', 'category', 'academic_year', 'is_active']
    search_fields = ['group__name', 'academic_year']
    list_select_related = ['branch', 'group', 'category']


@admin.register(StudentFeeAssignment)
class StudentFeeAssignmentAdmin(admin.ModelAdmin):
    list_display = ['student', 'fee_structure', 'final_amount', 'discount_amount', 'is_active']
    list_filter = ['is_active', 'fee_structure__category']
    search_fields = ['student__name', 'student__student_id']
    list_select_related = ['student', 'fee_structure']


@admin.register(FeeInstallment)
class FeeInstallmentAdmin(admin.ModelAdmin):
    list_display = ['assignment', 'installment_number', 'amount_due', 'due_date', 'is_fully_paid']
    list_filter = ['is_fully_paid', 'due_date']
    search_fields = ['assignment__student__name', 'assignment__student__student_id']
    readonly_fields = ['amount_paid', 'balance']


@admin.register(FeePayment)
class FeePaymentAdmin(admin.ModelAdmin):
    list_display = ['receipt_no', 'installment', 'amount_paid', 'mode', 'paid_by_staff', 'paid_on']
    list_filter = ['mode', 'paid_on']
    search_fields = ['receipt_no', 'installment__assignment__student__name', 'transaction_ref']
    readonly_fields = ['receipt_no']
    date_hierarchy = 'paid_on'


@admin.register(AdditionalCharge)
class AdditionalChargeAdmin(admin.ModelAdmin):
    list_display = ['assignment', 'description', 'amount', 'charge_date', 'is_paid']
    list_filter = ['is_paid', 'charge_date']
    search_fields = ['description', 'assignment__student__name', 'assignment__student__student_id']
    date_hierarchy = 'charge_date'