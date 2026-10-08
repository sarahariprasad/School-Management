"""
fee_payment/student_fee_profile.py

Student Fee Profile — a single consolidated view of everything the spec
asks for:

    Student ID, Student name, Parent/Guardian name, Class/Grade,
    Section/Program, Admission date, Monthly fee amount,
    Applicable discounts/concessions, Additional charges (if any),
    Current outstanding amount, Payment status, Last payment date,
    Next payment due date, and the refundable Security Deposit status.

Field mapping note
-------------------
This school's Student model (students/models.py) doesn't use "class" or
"section" — students belong to a single `group` (a dynamic therapy group,
not fixed Red/Green/Orange choices) and a `student_branch`. There's no
separate "grade" or "program" field. So:
    Class/Grade      -> student.group.name  (e.g. "Green")
    Section/Program   -> student.student_branch

Security deposit
-----------------
Shown as its own block (not folded into "current_outstanding", since a
held deposit is not a fee due — it's money the school is holding on the
family's behalf). Only the student's most recent deposit is shown; a
student should normally have at most one. The Terms & Conditions PDF is
always downloadable via security_deposit_terms_url, regardless of whether
the student has a deposit on file yet, so a prospective family can read
the policy before paying.

Inactive-student rule
----------------------
"Inactive student fee should not show until he is active." Enforced in
two places:
  1. StudentFeeProfileView.get_queryset() only serves is_active=True
     students — an inactive student's profile 404s.
  2. StudentFeeProfileListView (the directory staff browse) only lists
     is_active=True students.
build_student_fee_profile() itself doesn't re-check is_active — it
trusts the caller, so don't call it directly from anywhere that hasn't
already filtered for active students.
"""

from decimal import Decimal
from datetime import date

from django.db.models import Sum, Q
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import DetailView, ListView

from students.models import Student
from .models import (
    StudentFeeAssignment, FeeInstallment, FeePayment, AdditionalCharge,
    SecurityDeposit
)
from .helpers import get_student_display_id


def build_student_fee_profile(student: Student) -> dict:
    """Assemble the full fee profile dict for one student, across all of
    their *active* fee assignments. Caller must have already confirmed
    the student itself is active (see module docstring)."""

    assignments = StudentFeeAssignment.objects.filter(
        student=student, is_active=True
    ).select_related(
        'fee_structure', 'fee_structure__category',
        'fee_structure__branch', 'fee_structure__group'
    )

    monthly_fee_total = Decimal('0.00')
    discounts = []
    total_discount = Decimal('0.00')

    for assignment in assignments:
        # Billing is always the full final_amount each cycle (see
        # StudentFeeAssignment.generate_installments) — no conversion by
        # frequency here, since that would misrepresent what's actually
        # charged per installment.
        monthly_fee_total += assignment.final_amount
        if assignment.discount_amount and assignment.discount_amount > 0:
            discounts.append({
                'category': assignment.fee_structure.category.name,
                'amount': assignment.discount_amount,
                'reason': assignment.discount_reason,
            })
            total_discount += assignment.discount_amount

    installments = FeeInstallment.objects.filter(assignment__in=assignments)
    total_due = installments.aggregate(total=Sum('amount_due'))['total'] or Decimal('0.00')
    total_paid = FeePayment.objects.filter(
        installment__assignment__in=assignments
    ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

    charges = AdditionalCharge.objects.filter(assignment__in=assignments)
    charges_total = charges.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    charges_unpaid = charges.filter(is_paid=False).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    outstanding = (total_due - total_paid) + charges_unpaid

    last_payment = FeePayment.objects.filter(
        installment__assignment__in=assignments
    ).order_by('-paid_on').first()

    next_due = installments.filter(is_fully_paid=False).order_by('due_date').first()

    if total_due == 0:
        payment_status = "Not Generated"
    elif outstanding <= 0:
        payment_status = "No Dues"
    elif next_due and next_due.due_date < date.today():
        payment_status = "Overdue"
    else:
        payment_status = "Pending"

    parent_name_parts = [p for p in [student.father_name, student.mother_name] if p]
    parent_guardian_name = " / ".join(parent_name_parts) if parent_name_parts else "Not on file"

    group = getattr(student, "group", None)
    class_grade = group.name if group else "Not Assigned"

    # ---------- Security Deposit ----------
    deposit = SecurityDeposit.objects.filter(student=student).order_by('-paid_on').first()
    security_deposit = None
    if deposit:
        security_deposit = {
            'id': deposit.pk,
            'amount': deposit.amount,
            'status': deposit.status,
            'paid_on': deposit.paid_on,
            'receipt_no': deposit.receipt_no,
            'notice_period_days': deposit.notice_period_days,
            'notice_given_on': deposit.notice_given_on,
            'expected_refund_date': deposit.expected_refund_date,
            'refund_amount_due': deposit.refund_amount_due,
            'is_refunded': deposit.is_refunded,
            'refunded_on': deposit.refunded_on,
            'receipt_download_url': reverse(
                'fee_payment:security_deposit_receipt_download', kwargs={'pk': deposit.pk}
            ),
        }

    return {
        'student_id': get_student_display_id(student),
        'student_name': student.name,
        'parent_guardian_name': parent_guardian_name,
        'class_grade': class_grade,
        'section_program': str(student.student_branch) if student.student_branch else "Not Assigned",
        'admission_date': student.admission_date,
        'monthly_fee_amount': monthly_fee_total,
        'discounts': discounts,
        'total_discount': total_discount,
        'additional_charges': list(
            charges.values('description', 'amount', 'is_paid', 'charge_date')
        ),
        'additional_charges_total': charges_total,
        'current_outstanding': outstanding,
        'payment_status': payment_status,
        'last_payment_date': last_payment.paid_on if last_payment else None,
        'next_due_date': next_due.due_date if next_due else None,
        'assignments': assignments,
        'security_deposit': security_deposit,
        'security_deposit_terms_url': reverse('fee_payment:deposit_terms_download'),
    }


# ---------- Views ----------

class StudentFeeProfileView(LoginRequiredMixin, DetailView):
    """One student's consolidated fee profile. 404s for inactive students
    by construction — the queryset never contains them."""
    model = Student
    template_name = 'fee_payment/student_fee_profile.html'
    context_object_name = 'student'

    def get_queryset(self):
        return Student.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['profile'] = build_student_fee_profile(self.object)
        return context


class StudentFeeProfileListView(LoginRequiredMixin, ListView):
    """Searchable directory of active students, to jump into a profile.
    Inactive students never appear here either."""
    model = Student
    template_name = 'fee_payment/student_fee_profile_list.html'
    context_object_name = 'students'
    paginate_by = 30

    def get_queryset(self):
        qs = Student.objects.filter(is_active=True).select_related(
            'group', 'student_branch'
        ).order_by('name')
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(student_id__icontains=q))
        return qs