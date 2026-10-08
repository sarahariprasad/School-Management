"""
Forms for the fee payment system.
"""

import logging
from decimal import Decimal

from django import forms
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from .models import (
    FeeCategory, FeeStructure, StudentFeeAssignment,
    FeeInstallment, FeePayment, Frequency, SecurityDeposit, DepositPolicy
)
from staff.models import StaffProfile

logger = logging.getLogger(__name__)


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
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'],
        help_text="Leave blank to use today's date."
    )

    class Meta:
        model = FeeStructure
        fields = [
            'branch', 'group', 'category', 'academic_year',
            'frequency', 'start_date', 'amount', 'is_active'
        ]
        widgets = {
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'group': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'academic_year': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '2026-2027'}),
            'frequency': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['group'].required = False
        self.fields['group'].empty_label = "All groups (no restriction)"

class StudentFeeAssignmentForm(forms.ModelForm):
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'],
        help_text="Leave blank for School (uses Fee Structure date). Set for Day Care (student join date)."
    )

    discount_amount = forms.DecimalField(
        required=False,
        initial=Decimal('0.00'),
        min_value=Decimal('0.00'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        help_text="Enter discount amount (not percentage). Final amount = Fee amount - Discount."
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
            'discount_reason': forms.TextInput(attrs={'class': 'form-control'}),
            'parent_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'parent@example.com'}),
            'parent_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 98765 43210'}),
            'notify_parent': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'parent_email': 'Leave blank to use email from student record.',
            'parent_phone': 'Leave blank to use phone from student record.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'student' in self.fields:
            self.fields['student'].queryset = self.fields['student'].queryset.filter(
                is_active=True
            ).select_related('group', 'student_branch').order_by('name')

        if 'fee_structure' in self.fields:
            self.fields['fee_structure'].queryset = self.fields['fee_structure'].queryset.filter(
                is_active=True
            ).select_related('category', 'branch', 'group').order_by(
                'category__name', 'academic_year'
            )
            
    def clean_discount_amount(self):
        discount = self.cleaned_data.get('discount_amount') or Decimal('0.00')
        if discount < 0:
            raise forms.ValidationError(_("Discount amount cannot be negative."))
        return discount

    def clean(self):
        cleaned_data = super().clean()
        student = cleaned_data.get('student')
        fee_structure = cleaned_data.get('fee_structure')
        discount_amount = cleaned_data.get('discount_amount') or Decimal('0.00')
        discount_reason = cleaned_data.get('discount_reason')
        start_date = cleaned_data.get('start_date')

        # 1. Discount cannot exceed fee amount
        if fee_structure and discount_amount > fee_structure.amount:
            self.add_error(
                'discount_amount',
                _(
                    "Discount (₹%(discount)s) cannot exceed the fee amount (₹%(amount)s)."
                ) % {
                    'discount': discount_amount,
                    'amount': fee_structure.amount
                }
            )

        # 2. If discount given, reason is mandatory
        if discount_amount > 0 and not discount_reason:
            self.add_error(
                'discount_reason',
                _("Please provide a reason for the discount.")
            )

        # 3. Prevent duplicate active assignment for same student + fee structure
        if student and fee_structure:
            if student.student_branch_id != fee_structure.branch_id:
                self.add_error(
                    'fee_structure',
                    _("The selected fee structure belongs to a different branch than this student.")
                )
            if fee_structure.group_id and fee_structure.group_id != student.group_id:
                self.add_error(
                    'fee_structure',
                    _("The selected fee structure is for a different student group.")
                )
            dup_qs = StudentFeeAssignment.objects.filter(
                student=student,
                fee_structure=fee_structure,
                is_active=True
            )
            if self.instance and self.instance.pk:
                dup_qs = dup_qs.exclude(pk=self.instance.pk)
            
            if dup_qs.exists():
                self.add_error(
                    'fee_structure',
                    _(
                        "This student already has an active assignment for '%(fee)s'. "
                        "Please deactivate the existing one first."
                    ) % {'fee': fee_structure}
                )

        # 4. Day Care validation
        if fee_structure and 'day care' in fee_structure.category.name.lower():
            if not start_date:
                self.add_error(
                    'start_date',
                    _("Start date is required for Day Care fee assignments.")
                )

        if self.errors:
            logger.warning(
                "StudentFeeAssignmentForm validation failed. Errors: %s",
                dict(self.errors)
            )

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.discount_amount is None:
            instance.discount_amount = Decimal('0.00')
        
        if commit:
            instance.save()
        return instance


class FeeInstallmentForm(forms.ModelForm):
    class Meta:
        model = FeeInstallment
        fields = ['assignment', 'installment_number', 'amount_due', 'due_date']
        widgets = {
            'assignment': forms.Select(attrs={'class': 'form-select'}),
            'installment_number': forms.NumberInput(attrs={'class': 'form-control'}),
            'amount_due': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'due_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
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
        self.fields['installment'].queryset = FeeInstallment.objects.select_related(
            'assignment__student',
            'assignment__fee_structure__category'
        ).filter(
            is_fully_paid=False,
            assignment__is_active=True,
            assignment__student__is_active=True,
        )
        # An existing payment must remain selectable while it is being edited,
        # even when it made its installment fully paid.
        if self.instance and self.instance.pk:
            self.fields['installment'].queryset |= FeeInstallment.objects.filter(
                pk=self.instance.installment_id
            )

    def clean_amount_paid(self):
        amount = self.cleaned_data.get('amount_paid')
        installment = self.cleaned_data.get('installment')
        if installment and amount:
            existing_paid = FeePayment.objects.filter(installment=installment).exclude(
                pk=self.instance.pk
            ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
            remaining = installment.amount_due - existing_paid
            if amount > remaining:
                raise forms.ValidationError(
                    f"Amount paid (₹{amount}) cannot exceed remaining balance (₹{remaining})."
                )
        return amount

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            self._assign_paid_by_staff(instance)
        if commit:
            instance.save()
        return instance

    def _assign_paid_by_staff(self, instance):
        """
        Resolve the StaffProfile for the logged-in user. The previous version
        used hasattr(self.user, 'staffprofile'), which fails SILENTLY (no
        error, no log) whenever that isn't the exact related_name Django
        generated for the User<->StaffProfile link, or when the logged-in
        user simply has no StaffProfile row (e.g. a superuser account with no
        staff record) — paid_by_staff was quietly left as None with nothing
        indicating why. This tries the common access patterns and falls back
        to a direct query, and logs clearly when no profile is found at all,
        so a missing "recorded by" has a visible cause instead of failing
        silently.
        """
        staff_profile = getattr(self.user, 'staffprofile', None)
        if staff_profile is None:
            staff_profile = getattr(self.user, 'staff_profile', None)
        if staff_profile is None:
            staff_profile = StaffProfile.objects.filter(user=self.user).first()

        if staff_profile is None:
            logger.warning(
                "FeePaymentForm: no StaffProfile found for user %s (id=%s) — "
                "'paid_by_staff' will be left blank on this payment.",
                self.user, getattr(self.user, 'pk', None)
            )
        instance.paid_by_staff = staff_profile


# ═══════════════════════════════════════════════════════════════
# SECURITY DEPOSIT
# ═══════════════════════════════════════════════════════════════

class SecurityDepositForm(forms.ModelForm):
    """Records a new refundable deposit for a student."""

    class Meta:
        model = SecurityDeposit
        fields = [
            'student', 'amount', 'paid_on', 'mode', 'transaction_ref',
            'notice_period_days', 'remarks',
        ]
        widgets = {
            'student': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'paid_on': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'mode': forms.Select(attrs={'class': 'form-select'}),
            'transaction_ref': forms.TextInput(attrs={'class': 'form-control'}),
            'notice_period_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'student' in self.fields:
            self.fields['student'].queryset = self.fields['student'].queryset.filter(
                is_active=True
            ).order_by('name')
        # Pre-fill the notice period from the school's current policy so
        # staff don't have to look it up or retype it every time.
        if not self.instance.pk:
            self.fields['notice_period_days'].initial = DepositPolicy.get_current().notice_period_days

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise forms.ValidationError(_("Deposit amount must be greater than zero."))
        return amount


class DepositNoticeForm(forms.Form):
    """Used when a parent/guardian submits written notice of leaving."""
    notice_given_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        help_text="Leave blank to use today's date."
    )


class DepositRefundForm(forms.Form):
    """Used when actually processing the refund payout."""
    refunded_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        help_text="Leave blank to use today's date."
    )
    refund_mode = forms.ChoiceField(
        choices=FeePayment.PAYMENT_MODE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    refund_transaction_ref = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    deduction_amount = forms.DecimalField(
        required=False,
        initial=Decimal('0.00'),
        min_value=Decimal('0.00'),
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        help_text="Any amount withheld before refund (damages, dues, etc.). Leave blank for none."
    )
    deduction_reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    def clean(self):
        cleaned_data = super().clean()
        deduction_amount = cleaned_data.get('deduction_amount') or Decimal('0.00')
        if deduction_amount > 0 and not cleaned_data.get('deduction_reason'):
            self.add_error('deduction_reason', _("Please provide a reason for the deduction."))
        return cleaned_data