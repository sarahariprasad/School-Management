from decimal import Decimal
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import redirect
from django.db.models import (
    Q, Sum, F, DecimalField, Value, OuterRef, Subquery, Count
)
from django.db.models.functions import Coalesce, TruncDate
from django.views.generic import (
    ListView, CreateView, UpdateView, DeleteView, DetailView
)
from django.db import transaction
from django.utils import timezone
from datetime import date, timedelta
import logging

from students.models import Student
from .models import (
    FeeCategory, FeeStructure, StudentFeeAssignment,
    FeeInstallment, FeePayment, Frequency
)
from .forms import (
    FeeCategoryForm, FeeStructureForm, StudentFeeAssignmentForm,
    FeeInstallmentForm, FeePaymentForm
)
from .notifications import (
    send_payment_recorded_notification,
    send_fee_due_notification,
    send_due_reminder_notification
)
from .helpers import (
    build_student_search_filter,
    build_student_search_filter_installment,
    build_student_search_filter_payment,
    get_student_display_id,
    get_student_id_field_name,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# ROLE MIXINS (using your custom User model roles)
# ═══════════════════════════════════════════════════════════════

class FinanceAdminRequiredMixin(LoginRequiredMixin):
    """
    Allow only:
      - Superuser
      - SYSTEM_ADMIN
      - FINANCE_ADMIN
    Redirect others to dashboard with an error message.
    """

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
    """
    Any authenticated user with a valid role may access.
    Covers SYSTEM_ADMIN, FINANCE_ADMIN, BRANCH_ADMIN, and STAFF.
    """
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


class FeeCategoryCreateView(FinanceAdminRequiredMixin, CreateView):
    model = FeeCategory
    form_class = FeeCategoryForm
    template_name = 'fee_payment/fee_category_form.html'
    success_url = reverse_lazy('fee_payment:fee_category_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee category created successfully.")
        return super().form_valid(form)


class FeeCategoryUpdateView(FinanceAdminRequiredMixin, UpdateView):
    model = FeeCategory
    form_class = FeeCategoryForm
    template_name = 'fee_payment/fee_category_form.html'
    success_url = reverse_lazy('fee_payment:fee_category_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee category updated successfully.")
        return super().form_valid(form)


class FeeCategoryDeleteView(FinanceAdminRequiredMixin, DeleteView):
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
            'branch', 'class_name', 'category'
        )


class FeeStructureCreateView(FinanceAdminRequiredMixin, CreateView):
    model = FeeStructure
    form_class = FeeStructureForm
    template_name = 'fee_payment/fee_structure_form.html'
    success_url = reverse_lazy('fee_payment:fee_structure_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee structure created successfully.")
        return super().form_valid(form)


class FeeStructureUpdateView(FinanceAdminRequiredMixin, UpdateView):
    model = FeeStructure
    form_class = FeeStructureForm
    template_name = 'fee_payment/fee_structure_form.html'
    success_url = reverse_lazy('fee_payment:fee_structure_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee structure updated successfully.")
        return super().form_valid(form)


class FeeStructureDeleteView(FinanceAdminRequiredMixin, DeleteView):
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

        qs = super().get_queryset().select_related(
            'student',
            'fee_structure',
            'fee_structure__category',
            'fee_structure__branch',
            'fee_structure__class_name'
        ).annotate(
            total_due=Coalesce(
                Subquery(total_due_sq),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
            total_paid=Coalesce(
                Subquery(total_paid_sq),
                Value(Decimal('0.00')),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
        ).annotate(
            balance=F('total_due') - F('total_paid')
        )

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(
                build_student_search_filter(q) |
                Q(fee_structure__category__name__icontains=q)
            )

        status = self.request.GET.get('status')
        if status == 'paid':
            qs = qs.filter(balance__lte=0)
        elif status == 'pending':
            qs = qs.filter(balance__gt=0)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['student_id_field'] = get_student_id_field_name()
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
            'fee_structure__class_name'
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

        context['total_due'] = total_due
        context['total_paid'] = total_paid
        context['total_balance'] = total_due - total_paid
        context['overall_status'] = 'Paid' if (total_due - total_paid) <= 0 else 'Pending'

        context['all_payments'] = FeePayment.objects.filter(
            installment__assignment=self.object
        ).select_related(
            'installment',
            'paid_by_staff'
        ).order_by('-paid_on')

        context['notification_logs'] = self.object.notification_logs.select_related(
            'installment'
        ).order_by('-sent_at')[:10]

        context['student_id_field'] = get_student_id_field_name()
        context['student_display_id'] = get_student_display_id(self.object.student)

        return context


class StudentFeeAssignmentCreateView(FinanceAdminRequiredMixin, CreateView):
    model = StudentFeeAssignment
    form_class = StudentFeeAssignmentForm
    template_name = 'fee_payment/student_fee_assignment_form.html'
    success_url = reverse_lazy('fee_payment:student_fee_assignment_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee assignment created successfully.")
        return super().form_valid(form)


class StudentFeeAssignmentUpdateView(FinanceAdminRequiredMixin, UpdateView):
    model = StudentFeeAssignment
    form_class = StudentFeeAssignmentForm
    template_name = 'fee_payment/student_fee_assignment_form.html'
    success_url = reverse_lazy('fee_payment:student_fee_assignment_list')

    def form_valid(self, form):
        messages.success(self.request, "Fee assignment updated successfully.")
        return super().form_valid(form)


class StudentFeeAssignmentDeleteView(FinanceAdminRequiredMixin, DeleteView):
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
            qs = qs.filter(is_fully_paid=False, due_date__lt=date.today())

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


class FeeInstallmentCreateView(FinanceAdminRequiredMixin, CreateView):
    model = FeeInstallment
    form_class = FeeInstallmentForm
    template_name = 'fee_payment/fee_installment_form.html'
    success_url = reverse_lazy('fee_payment:fee_installment_list')

    def form_valid(self, form):
        messages.success(self.request, "Installment created successfully.")
        return super().form_valid(form)


class FeeInstallmentUpdateView(FinanceAdminRequiredMixin, UpdateView):
    model = FeeInstallment
    form_class = FeeInstallmentForm
    template_name = 'fee_payment/fee_installment_form.html'
    success_url = reverse_lazy('fee_payment:fee_installment_list')

    def form_valid(self, form):
        messages.success(self.request, "Installment updated successfully.")
        return super().form_valid(form)


class FeeInstallmentDeleteView(FinanceAdminRequiredMixin, DeleteView):
    model = FeeInstallment
    template_name = 'fee_payment/confirm_delete.html'
    success_url = reverse_lazy('fee_payment:fee_installment_list')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, "Installment deleted successfully.")
        return super().delete(request, *args, **kwargs)


# ═══════════════════════════════════════════════════════════════
# FEE PAYMENT (Admin / FinanceAdmin ONLY)
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


class FeePaymentCreateView(FinanceAdminRequiredMixin, CreateView):
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
        self.object = form.save()
        messages.success(
            self.request,
            f"Payment recorded. Receipt: {self.object.receipt_no}"
        )

        try:
            send_payment_recorded_notification(self.object)
        except Exception as e:
            logger.exception(
                "Failed to send payment notification for payment %s: %s",
                self.object.pk, e
            )
            messages.warning(
                self.request,
                "Payment saved but notification to parent failed. Please check logs."
            )

        return redirect(self.get_success_url())


class FeePaymentUpdateView(FinanceAdminRequiredMixin, UpdateView):
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


class FeePaymentDeleteView(FinanceAdminRequiredMixin, DeleteView):
    model = FeePayment
    template_name = 'fee_payment/confirm_delete.html'
    success_url = reverse_lazy('fee_payment:fee_payment_list')

    def delete(self, request, *args, **kwargs):
        payment = self.get_object()
        installment = payment.installment
        response = super().delete(request, *args, **kwargs)

        if installment.balance > 0 and installment.is_fully_paid:
            installment.is_fully_paid = False
            installment.save(update_fields=['is_fully_paid'])

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
            due_date__lte=reminder_window
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

        student_overdue_qs = FeeInstallment.objects.filter(
            is_fully_paid=False,
            due_date__lte=reminder_window
        ).values('assignment__student').annotate(
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
            inst_count = FeeInstallment.objects.filter(
                assignment__student=item['assignment__student'],
                is_fully_paid=False,
                due_date__lte=reminder_window
            ).count()

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
# REPORTS
# ═══════════════════════════════════════════════════════════════

class DailyCollectionReportView(FinanceAdminRequiredMixin, ListView):
    model = FeePayment
    template_name = 'fee_payment/daily_collection_report.html'
    context_object_name = 'daily_collections'
    paginate_by = 31

    def get_queryset(self):
        qs = FeePayment.objects.annotate(
            payment_date=TruncDate('paid_on')
        ).values('payment_date').annotate(
            total_amount=Sum('amount_paid'),
            transaction_count=Count('id')
        ).order_by('-payment_date')

        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if date_from:
            qs = qs.filter(payment_date__gte=date_from)
        if date_to:
            qs = qs.filter(payment_date__lte=date_to)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        payment_qs = FeePayment.objects.all()
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')

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
        context['date_from'] = date_from
        context['date_to'] = date_to
        context['today'] = date.today()
        return context