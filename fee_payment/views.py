from decimal import Decimal
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404
from django.http import FileResponse, Http404
from django.db.models import (
    Q, Sum, F, DecimalField, Value, OuterRef, Subquery, Count
)
from django.db.models.functions import Coalesce, TruncDate
from django.views.generic import (
    ListView, CreateView, UpdateView, DeleteView, DetailView, View
)
from django.db import transaction
from django.utils import timezone
from datetime import date, timedelta
import logging

from students.models import Student
from .models import (
    FeeCategory, FeeStructure, StudentFeeAssignment,
    FeeInstallment, FeePayment, Frequency, Invoice, InvoiceStatus
)
from .forms import (
    FeeCategoryForm, FeeStructureForm, StudentFeeAssignmentForm,
    FeeInstallmentForm, FeePaymentForm
)
from .notifications import (
    send_due_reminder_notification
)
from .helpers import (
    build_student_search_filter,
    build_student_search_filter_installment,
    build_student_search_filter_payment,
    get_student_display_id,
    get_student_id_field_name,
)
from core.mixins import (
    AuditableCreateMixin,
    AuditableUpdateMixin,
    AuditableDeleteMixin,
)
from . import reports
from . import invoices as invoice_utils

logger = logging.getLogger(__name__)


def overdue_installments(queryset, as_of=None):
    """Return unpaid installments overdue after the school's 10th-day grace period."""
    as_of = as_of or date.today()
    queryset = queryset.filter(due_date__lt=as_of)
    if as_of.day <= 10:
        queryset = queryset.exclude(due_date__year=as_of.year, due_date__month=as_of.month)
    return queryset


# ═══════════════════════════════════════════════════════════════
# ROLE MIXINS
# ═══════════════════════════════════════════════════════════════

class FinanceAdminRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        user = request.user
        if user.is_superuser or user.is_system_admin or user.is_finance_admin:
            return super().dispatch(request, *args, **kwargs)

        messages.error(
            request,
            "Access denied. Only System Admin and Finance Admin can access this."
        )
        return redirect("dashboard")


class StaffRequiredMixin(LoginRequiredMixin):
    pass


# ═══════════════════════════════════════════════════════════════
# FEE CATEGORY
# ═══════════════════════════════════════════════════════════════

class FeeCategoryListView(StaffRequiredMixin, ListView):
    model = FeeCategory
    template_name = 'fee_payment/fee_category_list.html'
    context_object_name = 'categories'
    paginate_by = 20

    def get_queryset(self):
        return super().get_queryset()


class FeeCategoryCreateView(AuditableCreateMixin, FinanceAdminRequiredMixin, CreateView):
    model = FeeCategory
    form_class = FeeCategoryForm
    template_name = 'fee_payment/fee_category_form.html'
    success_url = reverse_lazy('fee_payment:fee_category_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee category created successfully.")
        return super().form_valid(form)


class FeeCategoryUpdateView(AuditableUpdateMixin, FinanceAdminRequiredMixin, UpdateView):
    model = FeeCategory
    form_class = FeeCategoryForm
    template_name = 'fee_payment/fee_category_form.html'
    success_url = reverse_lazy('fee_payment:fee_category_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee category updated successfully.")
        return super().form_valid(form)


class FeeCategoryDeleteView(AuditableDeleteMixin, FinanceAdminRequiredMixin, DeleteView):
    model = FeeCategory
    template_name = 'fee_payment/confirm_delete.html'
    success_url = reverse_lazy('fee_payment:fee_category_list')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Fee category deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ═══════════════════════════════════════════════════════════════
# FEE STRUCTURE
# ═══════════════════════════════════════════════════════════════

class FeeStructureListView(StaffRequiredMixin, ListView):
    model = FeeStructure
    template_name = 'fee_payment/fee_structure_list.html'
    context_object_name = 'fee_structures'
    paginate_by = 20

    def get_queryset(self):
        return super().get_queryset().select_related(
            'branch', 'group', 'category'
        )


class FeeStructureCreateView(AuditableCreateMixin, FinanceAdminRequiredMixin, CreateView):
    model = FeeStructure
    form_class = FeeStructureForm
    template_name = 'fee_payment/fee_structure_form.html'
    success_url = reverse_lazy('fee_payment:fee_structure_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee structure created successfully.")
        return super().form_valid(form)


class FeeStructureUpdateView(AuditableUpdateMixin, FinanceAdminRequiredMixin, UpdateView):
    model = FeeStructure
    form_class = FeeStructureForm
    template_name = 'fee_payment/fee_structure_form.html'
    success_url = reverse_lazy('fee_payment:fee_structure_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee structure updated successfully.")
        return super().form_valid(form)


class FeeStructureDeleteView(AuditableDeleteMixin, FinanceAdminRequiredMixin, DeleteView):
    model = FeeStructure
    template_name = 'fee_payment/confirm_delete.html'
    success_url = reverse_lazy('fee_payment:fee_structure_list')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Fee structure deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ═══════════════════════════════════════════════════════════════
# STUDENT FEE ASSIGNMENT
# ═══════════════════════════════════════════════════════════════

class StudentFeeAssignmentListView(StaffRequiredMixin, ListView):
    model = StudentFeeAssignment
    template_name = 'fee_payment/student_fee_assignment_list.html'
    context_object_name = 'assignments'
    paginate_by = 20

    def get_queryset(self):
        total_due_sq = FeeInstallment.objects.filter(
            assignment=OuterRef('pk')
        ).values('assignment').annotate(
            total=Sum('amount_due')
        ).values('total')

        total_paid_sq = FeePayment.objects.filter(
            installment__assignment=OuterRef('pk')
        ).values('installment__assignment').annotate(
            total=Sum('amount_paid')
        ).values('total')

        overdue_sq = overdue_installments(FeeInstallment.objects.filter(
            assignment=OuterRef('pk'),
            is_fully_paid=False,
        )).values('assignment').annotate(cnt=Count('id')).values('cnt')

        qs = super().get_queryset().filter(
            student__is_active=True
        ).select_related(
            'student',
            'fee_structure',
            'fee_structure__category',
            'fee_structure__branch',
            'fee_structure__group'
        ).annotate(
            total_due_value=Coalesce(
                Subquery(total_due_sq),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
            total_paid_value=Coalesce(
                Subquery(total_paid_sq),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
            overdue_count=Coalesce(Subquery(overdue_sq), Value(0)),
        ).annotate(
            balance_value=F('total_due_value') - F('total_paid_value')
        )

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(
                build_student_search_filter(q) |
                Q(fee_structure__category__name__icontains=q)
            )

        status = self.request.GET.get('status')
        if status == 'paid':
            qs = qs.filter(total_due_value__gt=0, balance_value__lte=0)
        elif status == 'pending':
            qs = qs.filter(balance_value__gt=0)
        elif status == 'overdue':
            qs = qs.filter(overdue_count__gt=0)
        elif status == 'not_generated':
            qs = qs.filter(total_due_value=0)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['student_id_field'] = get_student_id_field_name()

        for assignment in context['assignments']:
            if assignment.total_due_value == 0:
                assignment.display_status = "Not Generated"
            elif assignment.overdue_count > 0:
                assignment.display_status = "Overdue"
            elif assignment.balance_value <= 0:
                assignment.display_status = "Paid"
            else:
                assignment.display_status = "Pending"

        return context


class StudentFeeAssignmentDetailView(StaffRequiredMixin, DetailView):
    model = StudentFeeAssignment
    template_name = 'fee_payment/student_fee_assignment_detail.html'
    context_object_name = 'assignment'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'student',
            'fee_structure',
            'fee_structure__category',
            'fee_structure__branch',
            'fee_structure__group'
        ).prefetch_related('notification_logs')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        installments = self.object.installments.prefetch_related(
            'payments',
            'payments__paid_by_staff'
        ).order_by('due_date')
        context['installments'] = installments

        total_due = sum(inst.amount_due for inst in installments)
        total_paid = sum(inst.amount_paid for inst in installments)
        has_overdue = any(inst.is_overdue for inst in installments)

        context['total_due'] = total_due
        context['total_paid'] = total_paid
        context['total_balance'] = total_due - total_paid

        if total_due == 0:
            context['overall_status'] = 'Not Generated'
        elif has_overdue:
            context['overall_status'] = 'Overdue'
        elif (total_due - total_paid) <= 0:
            context['overall_status'] = 'Paid'
        else:
            context['overall_status'] = 'Pending'

        context['current_month_status'] = self.object.current_month_status
        context['next_month_status'] = self.object.next_month_status

        context['all_payments'] = FeePayment.objects.filter(
            installment__assignment=self.object
        ).select_related(
            'installment',
            'paid_by_staff'
        ).order_by('-paid_on')

        context['notification_logs'] = self.object.notification_logs.select_related(
            'installment'
        ).order_by('-sent_at')[:10]

        context['invoices'] = self.object.invoices.order_by('-invoice_date')

        context['student_id_field'] = get_student_id_field_name()
        context['student_display_id'] = get_student_display_id(self.object.student)

        return context


class StudentFeeAssignmentCreateView(AuditableCreateMixin, FinanceAdminRequiredMixin, CreateView):
    model = StudentFeeAssignment
    form_class = StudentFeeAssignmentForm
    template_name = 'fee_payment/student_fee_assignment_form.html'
    success_url = reverse_lazy('fee_payment:student_fee_assignment_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.generate_installments()
        messages.success(self.request, "Fee assignment created successfully.")
        return response

    def form_invalid(self, form):
        logger.warning(
            "StudentFeeAssignmentCreateView: Form invalid. User: %s | Errors: %s",
            self.request.user,
            dict(form.errors)
        )
        messages.error(
            self.request,
            "Please correct the errors below. If the form looks empty after submitting, "
            "check the highlighted fields."
        )
        return super().form_invalid(form)


class StudentFeeAssignmentUpdateView(AuditableUpdateMixin, FinanceAdminRequiredMixin, UpdateView):
    model = StudentFeeAssignment
    form_class = StudentFeeAssignmentForm
    template_name = 'fee_payment/student_fee_assignment_form.html'
    success_url = reverse_lazy('fee_payment:student_fee_assignment_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.generate_installments()
        messages.success(self.request, "Fee assignment updated successfully.")
        return response

    def form_invalid(self, form):
        logger.warning(
            "StudentFeeAssignmentUpdateView: Form invalid. User: %s | PK: %s | Errors: %s",
            self.request.user,
            self.kwargs.get('pk'),
            dict(form.errors)
        )
        messages.error(
            self.request,
            "Please correct the errors below before saving."
        )
        return super().form_invalid(form)


class StudentFeeAssignmentDeleteView(AuditableDeleteMixin, FinanceAdminRequiredMixin, DeleteView):
    model = StudentFeeAssignment
    template_name = 'fee_payment/confirm_delete.html'
    success_url = reverse_lazy('fee_payment:student_fee_assignment_list')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Fee assignment deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ═══════════════════════════════════════════════════════════════
# FEE INSTALLMENT
# ═══════════════════════════════════════════════════════════════

class FeeInstallmentListView(StaffRequiredMixin, ListView):
    model = FeeInstallment
    template_name = 'fee_payment/fee_installment_list.html'
    context_object_name = 'installments'
    paginate_by = 20

    def get_queryset(self):
        total_paid_sq = FeePayment.objects.filter(
            installment=OuterRef('pk')
        ).values('installment').annotate(
            total=Sum('amount_paid')
        ).values('total')

        qs = FeeInstallment.objects.select_related(
            'assignment',
            'assignment__student',
            'assignment__fee_structure',
            'assignment__fee_structure__category'
        ).annotate(
            total_paid=Coalesce(
                Subquery(total_paid_sq),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
        ).annotate(
            remaining_balance=F('amount_due') - F('total_paid')
        )

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(build_student_search_filter_installment(q))

        status = self.request.GET.get('status')
        if status == 'paid':
            qs = qs.filter(is_fully_paid=True)
        elif status == 'pending':
            qs = qs.filter(is_fully_paid=False)
        elif status == 'overdue':
            qs = overdue_installments(qs.filter(is_fully_paid=False))

        due_from = self.request.GET.get('due_from')
        due_to = self.request.GET.get('due_to')
        if due_from:
            qs = qs.filter(due_date__gte=due_from)
        if due_to:
            qs = qs.filter(due_date__lte=due_to)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['student_id_field'] = get_student_id_field_name()
        return context


class FeeInstallmentCreateView(AuditableCreateMixin, FinanceAdminRequiredMixin, CreateView):
    model = FeeInstallment
    form_class = FeeInstallmentForm
    template_name = 'fee_payment/fee_installment_form.html'
    success_url = reverse_lazy('fee_payment:fee_installment_list')

    def form_valid(self, form):
        messages.success(self.request, "Installment created successfully.")
        return super().form_valid(form)


class FeeInstallmentUpdateView(AuditableUpdateMixin, FinanceAdminRequiredMixin, UpdateView):
    model = FeeInstallment
    form_class = FeeInstallmentForm
    template_name = 'fee_payment/fee_installment_form.html'
    success_url = reverse_lazy('fee_payment:fee_installment_list')

    def form_valid(self, form):
        messages.success(self.request, "Installment updated successfully.")
        return super().form_valid(form)


class FeeInstallmentDeleteView(AuditableDeleteMixin, FinanceAdminRequiredMixin, DeleteView):
    model = FeeInstallment
    template_name = 'fee_payment/confirm_delete.html'
    success_url = reverse_lazy('fee_payment:fee_installment_list')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Installment deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ═══════════════════════════════════════════════════════════════
# FEE PAYMENT
# ═══════════════════════════════════════════════════════════════

class FeePaymentListView(FinanceAdminRequiredMixin, ListView):
    model = FeePayment
    template_name = 'fee_payment/fee_payment_list.html'
    context_object_name = 'payments'
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            'installment',
            'installment__assignment',
            'installment__assignment__student',
            'installment__assignment__fee_structure__category',
            'paid_by_staff'
        ).order_by('-paid_on')

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(
                Q(receipt_no__icontains=q) |
                build_student_search_filter_payment(q) |
                Q(transaction_ref__icontains=q)
            )

        mode = self.request.GET.get('mode')
        if mode:
            qs = qs.filter(mode=mode)

        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if date_from:
            qs = qs.filter(paid_on__date__gte=date_from)
        if date_to:
            qs = qs.filter(paid_on__date__lte=date_to)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['student_id_field'] = get_student_id_field_name()
        return context


class FeePaymentListExportView(FinanceAdminRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        qs = FeePayment.objects.select_related(
            'installment__assignment__student',
            'installment__assignment__fee_structure__category',
            'paid_by_staff'
        ).order_by('-paid_on')

        q = request.GET.get('q')
        if q:
            qs = qs.filter(
                Q(receipt_no__icontains=q) |
                build_student_search_filter_payment(q) |
                Q(transaction_ref__icontains=q)
            )

        mode = request.GET.get('mode')
        if mode:
            qs = qs.filter(mode=mode)

        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        if date_from:
            qs = qs.filter(paid_on__date__gte=date_from)
        if date_to:
            qs = qs.filter(paid_on__date__lte=date_to)

        filename = f"fee_payments_{date_from or 'all'}_to_{date_to or 'all'}.xlsx"
        return reports.export_payment_ledger_excel(qs, filename=filename)


class FeePaymentDetailView(FinanceAdminRequiredMixin, DetailView):
    model = FeePayment
    template_name = 'fee_payment/fee_payment_detail.html'
    context_object_name = 'payment'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'installment__assignment__student',
            'installment__assignment__fee_structure__category',
            'paid_by_staff'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['student_id_field'] = get_student_id_field_name()
        context['student_display_id'] = get_student_display_id(
            self.object.installment.assignment.student
        )
        return context


class FeePaymentCreateView(AuditableCreateMixin, FinanceAdminRequiredMixin, CreateView):
    model = FeePayment
    form_class = FeePaymentForm
    template_name = 'fee_payment/fee_payment_form.html'
    success_url = reverse_lazy('fee_payment:fee_payment_list')

    def get_initial(self):
        initial = super().get_initial()
        installment_id = self.request.GET.get('installment')
        if installment_id and FeeInstallment.objects.filter(
            pk=installment_id,
            is_fully_paid=False,
            assignment__is_active=True,
            assignment__student__is_active=True,
        ).exists():
            initial['installment'] = installment_id
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        self._stamp_created(form.instance)
        self.object = form.save()
        messages.success(
            self.request,
            f"Payment recorded. Receipt: {self.object.receipt_no}"
        )

        try:
            from audit_log.services import log_audit, snapshot_instance
            log_audit(
                self.request.user, self.object, "CREATE",
                snapshot=snapshot_instance(self.object)
            )
        except Exception as e:
            logger.exception("Audit log (CREATE) failed for payment %s: %s", self.object.pk, e)

        # ── Auto-generate + email an invoice right after payment ──
        # Previously nothing ever called invoice_utils.create_invoice() on
        # the payment path — invoices only came from the separate manual
        # "Generate Invoice" button, which is why the Invoices page stayed
        # empty even after payments were recorded. A failure here must never
        # roll back or block the already-recorded payment, so it's isolated
        # in its own try/except and only surfaced as a warning message.
        try:
            installment = self.object.installment
            invoice = invoice_utils.create_invoice(
                assignment=installment.assignment,
                installment=installment,
                user=self.request.user,
            )
            try:
                log_audit(
                    self.request.user, invoice, "CREATE",
                    snapshot=snapshot_instance(invoice)
                )
            except Exception as e:
                logger.exception("Audit log (CREATE) failed for auto-invoice %s: %s", invoice.pk, e)

            if invoice_utils.send_invoice_email(invoice):
                messages.success(self.request, f"Invoice {invoice.invoice_no} generated and emailed.")
            else:
                messages.warning(
                    self.request,
                    f"Invoice {invoice.invoice_no} generated, but emailing it failed. "
                    "Check notification logs."
                )
        except Exception as e:
            logger.exception(
                "Auto-invoice generation failed after payment %s: %s",
                self.object.pk, e
            )
            messages.warning(
                self.request,
                "Payment was recorded, but automatic invoice generation failed. "
                "You can generate it manually from the assignment page."
            )

        return redirect(self.get_success_url())


class FeePaymentUpdateView(AuditableUpdateMixin, FinanceAdminRequiredMixin, UpdateView):
    model = FeePayment
    form_class = FeePaymentForm
    template_name = 'fee_payment/fee_payment_form.html'
    success_url = reverse_lazy('fee_payment:fee_payment_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        messages.success(self.request, "Payment updated successfully.")
        return super().form_valid(form)


class FeePaymentDeleteView(AuditableDeleteMixin, FinanceAdminRequiredMixin, DeleteView):
    model = FeePayment
    template_name = 'fee_payment/confirm_delete.html'
    success_url = reverse_lazy('fee_payment:fee_payment_list')

    def delete(self, request, *args, **kwargs):
        response = super().delete(request, *args, **kwargs)
        messages.success(self.request, "Payment deleted successfully.")
        return response


class FeePaymentReceiptView(FinanceAdminRequiredMixin, DetailView):
    model = FeePayment
    template_name = 'fee_payment/fee_payment_receipt.html'
    context_object_name = 'payment'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'installment__assignment__student',
            'installment__assignment__fee_structure',
            'installment__assignment__fee_structure__category',
            'installment__assignment__fee_structure__branch',
            'paid_by_staff'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['student_id_field'] = get_student_id_field_name()
        context['student_display_id'] = get_student_display_id(
            self.object.installment.assignment.student
        )
        return context


# ═══════════════════════════════════════════════════════════════
# ACCOUNTANT FEE-DUE SEARCH
# ═══════════════════════════════════════════════════════════════

class FeeDueSearchView(StaffRequiredMixin, ListView):
    model = StudentFeeAssignment
    template_name = 'fee_payment/fee_due_search.html'
    context_object_name = 'student_summary'
    paginate_by = 50

    def get_filtered_installments(self):
        qs = FeeInstallment.objects.filter(
            is_fully_paid=False,
            assignment__student__is_active=True
        )

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(build_student_search_filter_installment(q))

        branch = self.request.GET.get('branch')
        if branch:
            qs = qs.filter(assignment__fee_structure__branch_id=branch)

        group_id = self.request.GET.get('group')
        if group_id:
            qs = qs.filter(assignment__fee_structure__group_id=group_id)

        only_overdue = self.request.GET.get('overdue_only') == '1'
        if only_overdue:
            qs = overdue_installments(qs)

        due_from = self.request.GET.get('due_from')
        due_to = self.request.GET.get('due_to')
        if due_from:
            qs = qs.filter(due_date__gte=due_from)
        if due_to:
            qs = qs.filter(due_date__lte=due_to)

        return qs

    def build_student_summary(self):
        installments_qs = self.get_filtered_installments()

        grouped = installments_qs.values('assignment__student').annotate(
            total_due=Sum('amount_due'),
            total_paid=Coalesce(Sum('payments__amount_paid'), Value(Decimal('0.00'))),
            pending_count=Count('id', distinct=True),
        ).annotate(
            total_outstanding=F('total_due') - F('total_paid')
        ).filter(total_outstanding__gt=0)

        student_ids = [row['assignment__student'] for row in grouped]
        student_map = {s.pk: s for s in Student.objects.filter(pk__in=student_ids)}

        summary = []
        for row in grouped:
            student = student_map.get(row['assignment__student'])
            summary.append({
                'student': student,
                'student_display_id': get_student_display_id(student) if student else '',
                'installment_count': row['pending_count'],
                'total_overdue': row['total_outstanding'],
            })

        summary.sort(key=lambda x: x['total_overdue'], reverse=True)
        return summary

    def get_queryset(self):
        return self.build_student_summary()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '')
        context['overdue_only'] = self.request.GET.get('overdue_only') == '1'
        context['due_from'] = self.request.GET.get('due_from', '')
        context['due_to'] = self.request.GET.get('due_to', '')
        context['student_id_field'] = get_student_id_field_name()
        context['grand_total_outstanding'] = sum(
            row['total_overdue'] for row in context[self.context_object_name]
        ) if context.get(self.context_object_name) else Decimal('0.00')
        return context


class FeeDueSearchExportView(StaffRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        search_view = FeeDueSearchView()
        search_view.request = request
        summary = search_view.build_student_summary()
        return reports.export_overdue_report_excel(summary, filename="fee_due_search.xlsx")


# ═══════════════════════════════════════════════════════════════
# BULK NOTIFICATION VIEWS
# ═══════════════════════════════════════════════════════════════

class SendDueRemindersView(FinanceAdminRequiredMixin, ListView):
    model = FeeInstallment
    template_name = 'fee_payment/send_due_reminders.html'
    context_object_name = 'pending_installments'
    paginate_by = 50

    def get_queryset(self):
        today = date.today()
        reminder_window = today + timedelta(days=7)

        total_paid_sq = FeePayment.objects.filter(
            installment=OuterRef('pk')
        ).values('installment').annotate(
            total=Sum('amount_paid')
        ).values('total')

        return FeeInstallment.objects.select_related(
            'assignment__student',
            'assignment__fee_structure__category'
        ).filter(
            is_fully_paid=False,
            due_date__lte=reminder_window,
            assignment__student__is_active=True
        ).annotate(
            total_paid=Coalesce(
                Subquery(total_paid_sq),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
        ).annotate(
            remaining_balance=F('amount_due') - F('total_paid')
        ).order_by('due_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        reminder_window = today + timedelta(days=7)

        student_overdue_qs = overdue_installments(FeeInstallment.objects.filter(
            is_fully_paid=False,
            assignment__student__is_active=True
        )).values('assignment__student').annotate(
            total_due=Sum('amount_due'),
            total_paid=Coalesce(Sum('payments__amount_paid'), Value(Decimal('0.00')))
        ).annotate(
            total_overdue=F('total_due') - F('total_paid')
        ).filter(total_overdue__gt=0)

        student_ids = [item['assignment__student'] for item in student_overdue_qs]
        student_map = {
            s.pk: s for s in Student.objects.filter(pk__in=student_ids)
        }

        student_summary = []
        for item in student_overdue_qs:
            student = student_map.get(item['assignment__student'])
            inst_count = overdue_installments(FeeInstallment.objects.filter(
                assignment__student=item['assignment__student'],
                is_fully_paid=False,
            )).count()

            student_summary.append({
                'student': student,
                'student_display_id': get_student_display_id(student) if student else '',
                'installment_count': inst_count,
                'total_overdue': item['total_overdue'],
            })

        student_summary.sort(key=lambda x: x['total_overdue'], reverse=True)

        context['student_summary'] = student_summary
        context['grand_total_overdue'] = sum(s['total_overdue'] for s in student_summary)
        context['student_id_field'] = get_student_id_field_name()
        context['today'] = today
        context['reminder_window_date'] = reminder_window
        return context

    def post(self, request, *args, **kwargs):
        qs = self.get_queryset()
        sent_count = 0
        failed_count = 0

        for installment in qs:
            try:
                success = send_due_reminder_notification(installment)
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.exception(
                    "Reminder failed for installment %s: %s",
                    installment.pk, e
                )
                failed_count += 1

        if sent_count:
            messages.success(request, f"Sent {sent_count} due reminder(s).")
        if failed_count:
            messages.warning(
                request,
                f"Failed to send {failed_count} reminder(s). Check notification logs."
            )

        return redirect(request.path)


# ═══════════════════════════════════════════════════════════════
# INVOICES
# ═══════════════════════════════════════════════════════════════

class InvoiceListView(StaffRequiredMixin, ListView):
    model = Invoice
    template_name = 'fee_payment/invoice_list.html'
    context_object_name = 'invoices'
    paginate_by = 25

    def get_queryset(self):
        qs = Invoice.objects.select_related(
            'assignment__student',
            'assignment__fee_structure__category',
            'installment',
        ).order_by('-invoice_date', '-created_at')

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(
                Q(invoice_no__icontains=q) |
                Q(assignment__student__name__icontains=q)
            )

        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)

        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if date_from:
            qs = qs.filter(invoice_date__gte=date_from)
        if date_to:
            qs = qs.filter(invoice_date__lte=date_to)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['student_id_field'] = get_student_id_field_name()
        context['status_choices'] = InvoiceStatus.choices
        return context


class InvoiceDetailView(StaffRequiredMixin, DetailView):
    model = Invoice
    template_name = 'fee_payment/invoice_detail.html'
    context_object_name = 'invoice'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'assignment__student',
            'assignment__fee_structure__category',
            'assignment__fee_structure__branch',
            'installment',
        ).prefetch_related('notification_logs')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['student_id_field'] = get_student_id_field_name()
        context['student_display_id'] = get_student_display_id(self.object.assignment.student)
        return context


class InvoicePDFDownloadView(StaffRequiredMixin, View):
    def get(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(Invoice, pk=pk)
        if not invoice.pdf_file:
            raise Http404("This invoice has no PDF on file.")
        return FileResponse(
            invoice.pdf_file.open('rb'),
            as_attachment=True,
            filename=f"{invoice.invoice_no}.pdf",
        )


class GenerateInvoiceView(FinanceAdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        assignment_id = request.POST.get('assignment_id')
        installment_id = request.POST.get('installment_id')

        assignment = get_object_or_404(StudentFeeAssignment, pk=assignment_id)
        installment = None
        if installment_id:
            installment = get_object_or_404(FeeInstallment, pk=installment_id, assignment=assignment)

        invoice = invoice_utils.create_invoice(
            assignment=assignment,
            installment=installment,
            user=request.user,
        )

        try:
            from audit_log.services import log_audit, snapshot_instance
            log_audit(request.user, invoice, "CREATE", snapshot=snapshot_instance(invoice))
        except Exception as e:
            logger.exception("Audit log (CREATE) failed for invoice %s: %s", invoice.pk, e)

        messages.success(request, f"Invoice {invoice.invoice_no} generated.")

        if request.POST.get('send_now') == '1':
            sent = invoice_utils.send_invoice_email(invoice)
            if sent:
                messages.success(request, f"Invoice {invoice.invoice_no} emailed to parent.")
            else:
                messages.warning(request, f"Invoice generated but email delivery failed. Check notification logs.")

        next_url = request.POST.get('next') or reverse_lazy('fee_payment:invoice_detail', kwargs={'pk': invoice.pk})
        return redirect(next_url)


class SendInvoiceEmailView(FinanceAdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(Invoice, pk=pk)
        sent = invoice_utils.send_invoice_email(invoice)
        if sent:
            messages.success(request, f"Invoice {invoice.invoice_no} emailed to parent.")
        else:
            messages.warning(request, "Failed to email invoice. Check notification logs.")
        next_url = request.POST.get('next') or reverse_lazy('fee_payment:invoice_detail', kwargs={'pk': invoice.pk})
        return redirect(next_url)


class InvoiceCancelView(AuditableUpdateMixin, FinanceAdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(Invoice, pk=pk)
        invoice.status = InvoiceStatus.CANCELLED
        invoice.updated_by = request.user
        invoice.save(update_fields=['status', 'updated_by', 'updated_at'])
        messages.success(request, f"Invoice {invoice.invoice_no} cancelled.")
        return redirect('fee_payment:invoice_detail', pk=invoice.pk)


# ═══════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════

class DailyCollectionReportView(FinanceAdminRequiredMixin, ListView):
    model = FeePayment
    template_name = 'fee_payment/daily_collection_report.html'
    context_object_name = 'daily_collections'
    paginate_by = 31

    def _resolve_range(self):
        period = self.request.GET.get('period', 'daily')
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')

        if not date_from and not date_to and period != 'custom':
            date_from, date_to = reports.default_range_for_period(period)

        return period, date_from, date_to

    def get_queryset(self):
        period, date_from, date_to = self._resolve_range()
        return reports.get_collection_report_queryset(period, date_from, date_to)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period, date_from, date_to = self._resolve_range()

        payment_qs = FeePayment.objects.all()
        if date_from:
            payment_qs = payment_qs.filter(paid_on__date__gte=date_from)
        if date_to:
            payment_qs = payment_qs.filter(paid_on__date__lte=date_to)

        aggregates = payment_qs.aggregate(
            grand_total=Coalesce(Sum('amount_paid'), Value(Decimal('0.00'))),
            total_transactions=Count('id')
        )

        context['grand_total'] = aggregates['grand_total']
        context['total_transactions'] = aggregates['total_transactions']
        context['period'] = period
        context['date_from'] = date_from
        context['date_to'] = date_to
        context['today'] = date.today()
        return context


class FeeCollectionReportExportView(FinanceAdminRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        period = request.GET.get('period', 'daily')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')

        if not date_from and not date_to and period != 'custom':
            date_from, date_to = reports.default_range_for_period(period)

        return reports.export_collection_report_excel(period, date_from, date_to)


class DateRangePaymentReportView(FinanceAdminRequiredMixin, ListView):
    model = FeePayment
    template_name = 'fee_payment/date_range_payment_report.html'
    context_object_name = 'payments'
    paginate_by = 50

    def get_queryset(self):
        qs = FeePayment.objects.select_related(
            'installment__assignment__student',
            'installment__assignment__fee_structure__category',
            'paid_by_staff'
        ).order_by('-paid_on')

        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to', date.today().isoformat())
        if date_from:
            qs = qs.filter(paid_on__date__gte=date_from)
        if date_to:
            qs = qs.filter(paid_on__date__lte=date_to)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        aggregates = self.get_queryset().aggregate(
            grand_total=Coalesce(Sum('amount_paid'), Value(Decimal('0.00'))),
            total_transactions=Count('id')
        )
        context['grand_total'] = aggregates['grand_total']
        context['total_transactions'] = aggregates['total_transactions']
        context['date_from'] = self.request.GET.get('date_from', '')
        context['date_to'] = self.request.GET.get('date_to', date.today().isoformat())
        context['student_id_field'] = get_student_id_field_name()
        return context


class DateRangePaymentReportExportView(FinanceAdminRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        view = DateRangePaymentReportView()
        view.request = request
        qs = view.get_queryset()
        date_from = request.GET.get('date_from', 'start')
        date_to = request.GET.get('date_to', date.today().isoformat())
        filename = f"fee_payments_{date_from}_to_{date_to}.xlsx"
        return reports.export_payment_ledger_excel(qs, filename=filename)