"""
Forms for the fee payment system.
"""

from django import forms
from .models import (
    FeeCategory, FeeStructure, StudentFeeAssignment,
    FeeInstallment, FeePayment, Frequency
)


class FeeCategoryForm(forms.ModelForm):
    class Meta:
        model = FeeCategory
        fields = ['name', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class FeeStructureForm(forms.ModelForm):
    # Override start_date to make it optional — model default handles empty values
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'],
        help_text="Leave blank to use today's date."
    )

    class Meta:
        model = FeeStructure
        fields = [
            'branch', 'class_name', 'category', 'academic_year',
            'frequency', 'start_date', 'amount', 'is_active'
        ]
        widgets = {
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'class_name': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'academic_year': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '2026-2027'}),
            'frequency': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class StudentFeeAssignmentForm(forms.ModelForm):
    # Override start_date to make it optional
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'],
        help_text="Leave blank for School (uses Fee Structure date). Set for Day Care (student join date)."
    )

    class Meta:
        model = StudentFeeAssignment
        fields = [
            'student', 'fee_structure', 'discount_amount',
            'discount_reason', 'start_date',
            'parent_email', 'parent_phone',
            'notify_parent', 'is_active'
        ]
        widgets = {
            'student': forms.Select(attrs={'class': 'form-select'}),
            'fee_structure': forms.Select(attrs={'class': 'form-select'}),
            'discount_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'discount_reason': forms.TextInput(attrs={'class': 'form-control'}),
            'parent_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'parent@example.com'}),
            'parent_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 98765 43210'}),
            'notify_parent': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'parent_email': 'Leave blank to use email from student record.',
            'parent_phone': 'Leave blank to use phone from student record.',
            'discount_amount': 'Enter discount amount (not percentage). Final amount = Fee amount - Discount.',
        }


class FeeInstallmentForm(forms.ModelForm):
    class Meta:
        model = FeeInstallment
        fields = ['assignment', 'installment_number', 'amount_due', 'due_date', 'is_fully_paid']
        widgets = {
            'assignment': forms.Select(attrs={'class': 'form-select'}),
            'installment_number': forms.NumberInput(attrs={'class': 'form-control'}),
            'amount_due': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_fully_paid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class FeePaymentForm(forms.ModelForm):
    class Meta:
        model = FeePayment
        fields = ['installment', 'amount_paid', 'mode', 'transaction_ref', 'remarks']
        widgets = {
            'installment': forms.Select(attrs={'class': 'form-select'}),
            'amount_paid': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'mode': forms.Select(attrs={'class': 'form-select'}),
            'transaction_ref': forms.TextInput(attrs={'class': 'form-control'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        # Optimize installment queryset
        self.fields['installment'].queryset = FeeInstallment.objects.select_related(
            'assignment__student',
            'assignment__fee_structure__category'
        ).filter(is_fully_paid=False)

    def clean_amount_paid(self):
        amount = self.cleaned_data.get('amount_paid')
        installment = self.cleaned_data.get('installment')
        if installment and amount:
            if amount > installment.balance:
                raise forms.ValidationError(
                    f"Amount paid (₹{amount}) cannot exceed remaining balance (₹{installment.balance})."
                )
        return amount

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user and hasattr(self.user, 'staffprofile'):
            instance.paid_by_staff = self.user.staffprofile
        if commit:
            instance.save()
        return instance