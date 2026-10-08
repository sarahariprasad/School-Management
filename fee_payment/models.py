from django.db import models, transaction
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.mail import EmailMessage
from django.conf import settings
from decimal import Decimal
from datetime import date, timedelta
from calendar import monthrange
from dateutil.relativedelta import relativedelta
import logging
from django.db.models import Sum, Max
from django.core.exceptions import ValidationError
from core.mixins import TrackableMixin


from students.models import Student
from branches.models import Branch
from staff.models import StaffProfile

logger = logging.getLogger(__name__)


# ---------- Choices ----------

class Frequency(models.TextChoices):
    MONTHLY = 'monthly', 'Monthly'
    QUARTERLY = 'quarterly', 'Quarterly'
    HALF_YEARLY = 'half_yearly', 'Half Yearly'
    YEARLY = 'yearly', 'Yearly'


class NotificationType(models.TextChoices):
    FEE_DUE = 'fee_due', 'Fee Due'
    PAYMENT_RECORDED = 'payment_recorded', 'Payment Recorded'
    DUE_REMINDER = 'due_reminder', 'Due Reminder'
    OVERDUE = 'overdue', 'Overdue Notice'
    INVOICE_SENT = 'invoice_sent', 'Invoice Sent'


class Channel(models.TextChoices):
    EMAIL = 'email', 'Email'
    SMS = 'sms', 'SMS'
    PUSH = 'push', 'Push Notification'


class InvoiceStatus(models.TextChoices):
    GENERATED = 'generated', 'Generated'
    SENT = 'sent', 'Sent'
    CANCELLED = 'cancelled', 'Cancelled'


# ---------- Utility ----------

def add_months(d: date, months: int) -> date:
    """Add months to a date, handling year rollover and month-end."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


# ---------- Models ----------
# NOTE: All concrete models below now inherit TrackableMixin (core.mixins)
# instead of a locally-defined UserTrackingModel. Same fields
# (created_by/updated_by/created_at/updated_at), same created_by_display/
# updated_by_display properties — just one shared mixin app-wide instead of
# a fee_payment-only duplicate. This changes each model's related_name from
# '+' to '<modelname>_created' / '<modelname>_updated', so a migration is
# required (see notes at the end of this file).

class FeeCategory(TrackableMixin, models.Model):
    name = models.CharField(max_length=50, unique=True, db_index=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Fee Category'
        verbose_name_plural = 'Fee Categories'

    def __str__(self):
        return self.name

class FeeStructure(TrackableMixin, models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name='branch_fee_structures'
    )
    group = models.ForeignKey(
        'students.Group',
        on_delete=models.CASCADE,
        related_name='group_fee_structures',
        null=True,
        blank=True,
        help_text="Leave blank for a fee that applies regardless of group.",
    )
    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.PROTECT,
        related_name='fee_structures'
    )
    academic_year = models.CharField(max_length=9, db_index=True)  # e.g. "2026-2027"
    frequency = models.CharField(
        max_length=20,
        choices=Frequency.choices,
        default=Frequency.YEARLY,
        db_index=True,
        help_text="Determines how many installments are auto-generated per assignment."
    )
    start_date = models.DateField(
        default=date.today,
        help_text="Date when the first installment is due. All subsequent due dates are calculated from this."
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        unique_together = ('branch', 'group', 'category', 'academic_year')
        ordering = ['branch', 'group', 'category']
        indexes = [
            models.Index(fields=['academic_year', 'is_active']),
            models.Index(fields=['branch', 'group', 'is_active']),
        ]
        verbose_name = 'Fee Structure'
        verbose_name_plural = 'Fee Structures'

    def __str__(self):
        group_label = self.group.get_name_display() if self.group else "All Groups"
        return f"{self.branch} - {group_label} - {self.category} ({self.academic_year})"


class StudentFeeAssignment(TrackableMixin, models.Model):
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='fee_assignments'
    )
    fee_structure = models.ForeignKey(
        FeeStructure,
        on_delete=models.PROTECT,
        related_name='assignments'
    )
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)]
    )
    discount_reason = models.CharField(max_length=255, blank=True)
    final_amount = models.DecimalField(max_digits=10, decimal_places=2, editable=False)

    # Start date for this specific student (overrides fee_structure.start_date)
    # Used for Day Care where each student joins on a different date
    start_date = models.DateField(
        blank=True,
        null=True,
        help_text="Leave blank to use the Fee Structure start date. Set this for Day Care students who join on a specific date."
    )

    # Parent contact overrides (fallback to student.parent_email if blank)
    parent_email = models.EmailField(blank=True, help_text="Leave blank to use student record email.")
    parent_phone = models.CharField(max_length=20, blank=True, help_text="Leave blank to use student record phone.")
    notify_parent = models.BooleanField(default=True, help_text="Send fee notifications to parent.")

    is_active = models.BooleanField(default=True, db_index=True)

    # --- Hold / resume tracking ---
    hold_reason = models.CharField(
        max_length=255,
        blank=True,
        help_text="Why this assignment is on hold. Shown to staff/parents when is_active is False."
    )
    held_on = models.DateField(
        blank=True, null=True, editable=False,
        help_text="Auto-set to today when the assignment is switched to inactive/hold."
    )
    resumed_on = models.DateField(
        blank=True, null=True, editable=False,
        help_text="Auto-set to today when the assignment is switched back to active."
    )

    class Meta:
        unique_together = ('student', 'fee_structure')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['student', 'is_active']),
            models.Index(fields=['fee_structure', 'is_active']),
        ]
        verbose_name = 'Student Fee Assignment'
        verbose_name_plural = 'Student Fee Assignments'

    def save(self, *args, **kwargs):
        raw = self.fee_structure.amount - self.discount_amount
        self.final_amount = raw if raw > 0 else Decimal('0.00')

        # Track hold/resume transitions
        if self.pk:
            previous = StudentFeeAssignment.objects.filter(pk=self.pk).values('is_active').first()
            if previous is not None:
                was_active = previous['is_active']
                if was_active and not self.is_active:
                    self.held_on = date.today()
                    self.resumed_on = None
                elif (not was_active) and self.is_active:
                    self.resumed_on = date.today()
                    self.held_on = None

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.fee_structure.category} - ₹{self.final_amount}"

    # ---------- Installment Generation ----------

    def generate_installments(self):
        """
        Generate installments for the current billing period and the next one.

        The billing period is anchored to the assignment/structure start date.
        This is important for an autism school where monthly therapy, quarterly
        reviews, and annual programme fees must not all be billed monthly.
        No installments are generated while the assignment is inactive/on hold —
        this means resuming a student never backdates fees for the hold period;
        billing simply picks back up from whichever month generate_installments()
        is next called in.
        """

        if not self.is_active:
            logger.info(
                "Assignment %s is inactive/on hold (%s). Skipping installment generation.",
                self.pk, self.hold_reason or "no reason given"
            )
            return

        amount = self.final_amount
        start_date = self.start_date or self.fee_structure.start_date

        today = date.today()

        # Student has not joined yet
        if start_date > today:
            logger.info(
                "Student has not joined yet for assignment %s.",
                self.pk
            )
            return

        interval_months = {
            Frequency.MONTHLY: 1,
            Frequency.QUARTERLY: 3,
            Frequency.HALF_YEARLY: 6,
            Frequency.YEARLY: 12,
        }[self.fee_structure.frequency]

        # Find the billing date immediately before or on today, while keeping
        # the original day-of-month (for example, the 15th of each month).
        current_due_date = start_date
        while add_months(current_due_date, interval_months) <= today:
            current_due_date = add_months(current_due_date, interval_months)

        due_dates = [current_due_date, add_months(current_due_date, interval_months)]

        installments = []

        next_installment_number = (
            self.installments.aggregate(max_number=Max('installment_number'))['max_number'] or 0
        )
        for due_date in due_dates:
            # Avoid duplicate installment
            if self.installments.filter(due_date=due_date).exists():
                continue
            next_installment_number += 1
            installments.append(
                FeeInstallment(
                    assignment=self,
                    installment_number=next_installment_number,
                    amount_due=amount,
                    due_date=due_date,
                )
            )

        if installments:
            FeeInstallment.objects.bulk_create(installments)

            logger.info(
                "Generated %d installments for assignment %s.",
                len(installments),
                self.pk,
            )

    # ---------- Hold / Resume helpers ----------

    def put_on_hold(self, reason=""):
        """Mark this assignment inactive and record why. No new installments
        will be generated (existing unpaid ones remain visible/overdue)."""
        self.is_active = False
        self.hold_reason = reason
        self.save()

    def resume(self):
        """Reactivate the assignment. Fee generation will resume from
        whatever month generate_installments() is next called in — nothing
        is backdated for the hold period."""
        self.is_active = True
        self.hold_reason = ""
        self.save()
        self.generate_installments()

    # ---------- Status for dashboards ----------

    def _installment_for_month(self, month_date):
        return self.installments.filter(
            due_date__year=month_date.year,
            due_date__month=month_date.month,
        ).first()

    @property
    def current_month_installment(self):
        return self._installment_for_month(date.today().replace(day=1))

    @property
    def next_month_installment(self):
        next_month = date.today().replace(day=1) + relativedelta(months=1)
        return self._installment_for_month(next_month)

    @property
    def current_month_status(self):
        """What to show on the parent/staff dashboard for THIS month."""
        if not self.is_active:
            return f"Inactive / On Hold" + (f" — {self.hold_reason}" if self.hold_reason else "")

        inst = self.current_month_installment
        return inst.status if inst else "Not Generated"

    @property
    def next_month_status(self):
        """What to show on the parent/staff dashboard for NEXT month."""
        if not self.is_active:
            return "Inactive / On Hold"

        inst = self.next_month_installment
        return inst.status if inst else "Upcoming"

    @property
    def effective_parent_email(self):
        return (
            self.parent_email
            or getattr(self.student, "father_email", None)
            or getattr(self.student, "mother_email", None)
        )

    @property
    def effective_parent_phone(self):
        return (
            self.parent_phone
            or getattr(self.student, 'father_phone', None)
            or getattr(self.student, 'mother_phone', None)
        )

    @property
    def total_due(self):
        return self.installments.aggregate(total=models.Sum('amount_due'))['total'] or Decimal('0.00')

    @property
    def total_paid(self):
        return FeePayment.objects.filter(installment__assignment=self).aggregate(
            total=models.Sum('amount_paid')
        )['total'] or Decimal('0.00')

    @property
    def total_balance(self):
        return self.total_due - self.total_paid


class FeeInstallment(TrackableMixin, models.Model):
    assignment = models.ForeignKey(
        StudentFeeAssignment,
        on_delete=models.CASCADE,
        related_name='installments'
    )
    installment_number = models.PositiveIntegerField(default=1)
    amount_due = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    due_date = models.DateField(db_index=True)
    is_fully_paid = models.BooleanField(default=False, db_index=True)

    class Meta:
        unique_together = ('assignment', 'installment_number')
        ordering = ['due_date']
        indexes = [
            models.Index(fields=['due_date', 'is_fully_paid']),
            models.Index(fields=['assignment', 'is_fully_paid']),
        ]
        verbose_name = 'Fee Installment'
        verbose_name_plural = 'Fee Installments'

    def save(self, *args, **kwargs):
        """Keep the paid flag derived from payments, never manually set."""
        super().save(*args, **kwargs)
        self.refresh_paid_status()

    def refresh_paid_status(self):
        should_be_paid = self.balance <= Decimal('0.00')
        if self.is_fully_paid != should_be_paid:
            type(self).objects.filter(pk=self.pk).update(is_fully_paid=should_be_paid)
            self.is_fully_paid = should_be_paid

    @property
    def amount_paid(self):
        return self.payments.aggregate(total=models.Sum('amount_paid'))['total'] or Decimal('0.00')

    @property
    def balance(self):
        return self.amount_due - self.amount_paid

    @property
    def overdue_after(self):
        """The school gives families until the 10th of the billing month."""
        grace_date = self.due_date.replace(day=10)
        return max(self.due_date, grace_date)

    @property
    def is_overdue(self):
        # It becomes overdue on the 11th when its due date is on/before the
        # 10th; later configured due dates retain their later deadline.
        return not self.is_fully_paid and date.today() > self.overdue_after

    @property
    def status(self):
        """
        Simple label for UI use:
        Paid / Upcoming / Overdue / Overdue (Partially Paid)
        Note: is_active/hold state is NOT checked here — check it at the
        StudentFeeAssignment level (current_month_status / next_month_status)
        since a hold should override whatever an individual installment says.
        """
        if self.is_fully_paid:
            return "Paid"
        if self.due_date > date.today():
            return "Upcoming"
        if self.is_overdue and self.amount_paid > 0:
            return "Overdue (Partially Paid)"
        if self.is_overdue:
            return "Overdue"
        return "Pending"

    def __str__(self):
        return f"{self.assignment.student} - Inst {self.installment_number} (Due: {self.due_date})"

class FeePayment(TrackableMixin, models.Model):
    PAYMENT_MODE_CHOICES = [
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
        ('bank_transfer', 'Bank Transfer'),
        ('upi', 'UPI'),
        ('card', 'Card'),
    ]

    installment = models.ForeignKey(
        FeeInstallment,
        on_delete=models.PROTECT,
        related_name='payments'
    )
    amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default='cash', db_index=True)
    transaction_ref = models.CharField(max_length=100, blank=True, db_index=True)
    receipt_no = models.CharField(max_length=30, unique=True, editable=False, db_index=True)
    # Staff who physically collected/recorded the payment (distinct from
    # created_by/updated_by, which is the logged-in auth user — usually the
    # same person, but kept separate since paid_by_staff is domain data).
    paid_by_staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.SET_NULL,
        null=True,
        related_name='fee_payments_recorded'
    )
    paid_on = models.DateTimeField(default=timezone.now, db_index=True)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-paid_on']
        indexes = [
            models.Index(fields=['receipt_no', 'paid_on']),
            models.Index(fields=['installment', 'paid_on']),
        ]
        verbose_name = 'Fee Payment'
        verbose_name_plural = 'Fee Payments'

    @staticmethod
    def refresh_installment_paid_status(installment_id):
        """Synchronise the cached paid flag after any payment change."""
        if not installment_id:
            return
        installment = FeeInstallment.objects.get(pk=installment_id)
        installment.refresh_paid_status()

    def clean(self):
        super().clean()
        if not self.installment_id or self.amount_paid is None:
            return
        existing_paid = FeePayment.objects.filter(installment=self.installment).exclude(
            pk=self.pk
        ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
        remaining = self.installment.amount_due - existing_paid
        if self.amount_paid > remaining:
            raise ValidationError({
                'amount_paid': f"Amount paid cannot exceed the remaining balance (₹{remaining})."
            })

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        previous_installment_id = None
        if not is_new:
            previous_installment_id = type(self).objects.filter(pk=self.pk).values_list(
                'installment_id', flat=True
            ).first()
        if not self.receipt_no:
            # Use atomic counter to avoid duplicate receipt numbers under load
            self.receipt_no = f"RCPT{timezone.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"
        super().save(*args, **kwargs)

        self.refresh_installment_paid_status(previous_installment_id)
        self.refresh_installment_paid_status(self.installment_id)

        if is_new:
            self.send_receipt_email()

    def send_receipt_email(self):
        """Email the parent a payment confirmation. Failure here must never
        break the payment flow — the payment is already saved by this point,
        so we only log and move on if mail sending fails."""
        assignment = self.installment.assignment
        if not assignment.notify_parent:
            return
        recipient = assignment.effective_parent_email
        if not recipient:
            logger.info(
                "No parent email on file for assignment %s — skipping payment receipt email.",
                assignment.pk
            )
            return

        subject = f"Payment Received — Receipt {self.receipt_no}"
        message = (
            f"Dear Parent/Guardian,\n\n"
            f"We have received a payment of ₹{self.amount_paid} for "
            f"{assignment.student.name} towards {assignment.fee_structure.category}.\n\n"
            f"Please find your receipt attached as a PDF.\n\n"
            f"Thank you.\n"
        )
        try:
            # Local import avoids a circular import: pdf_utils doesn't need
            # anything from models.py, but models.py is imported very early
            # (by almost everything else in the app), so importing pdf_utils
            # at module level here would risk import-order issues.
            from .pdf_utils import generate_receipt_pdf
            pdf_bytes = generate_receipt_pdf(self)

            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                to=[recipient],
            )
            email.attach(f"{self.receipt_no}.pdf", pdf_bytes, 'application/pdf')
            email.send(fail_silently=False)
            logger.info("Payment receipt email (with PDF) sent to %s for receipt %s.", recipient, self.receipt_no)
        except Exception as e:
            logger.exception(
                "Failed to send payment receipt email for receipt %s: %s",
                self.receipt_no, e
            )

    def delete(self, *args, **kwargs):
        installment_id = self.installment_id
        result = super().delete(*args, **kwargs)
        self.refresh_installment_paid_status(installment_id)
        return result

    def __str__(self):
        return f"{self.receipt_no} - {self.installment.assignment.student} - ₹{self.amount_paid}"

    @property
    def recorded_by_display(self):
        """
        What to show in a "Recorded By" column. Falls back to the logged-in
        user (created_by, always set) when there's no linked StaffProfile —
        e.g. an admin/superuser account recording a payment without having
        a staff record of their own. Use this in templates instead of
        payment.paid_by_staff.full_name directly.
        """
        if self.paid_by_staff:
            return getattr(self.paid_by_staff, 'full_name', None) or str(self.paid_by_staff)
        if self.created_by:
            return self.created_by.get_full_name() or self.created_by.email
        return "System"


# ---------- Invoices ----------

class Invoice(TrackableMixin, models.Model):
    """
    A generated invoice for a fee assignment (or a specific installment).
    The PDF is rendered once at generation time and stored in pdf_file so
    re-downloading later doesn't require re-rendering.
    """
    assignment = models.ForeignKey(
        StudentFeeAssignment,
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    installment = models.ForeignKey(
        FeeInstallment,
        on_delete=models.CASCADE,
        related_name='invoices',
        null=True,
        blank=True,
        help_text="Leave blank for a full-assignment invoice covering all installments."
    )
    invoice_no = models.CharField(max_length=30, unique=True, editable=False, db_index=True)
    invoice_date = models.DateField(default=date.today, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.GENERATED,
        db_index=True,
    )
    pdf_file = models.FileField(upload_to='fee_invoices/%Y/%m/', blank=True, null=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-invoice_date', '-created_at']
        indexes = [
            models.Index(fields=['assignment', '-invoice_date']),
            models.Index(fields=['status', '-invoice_date']),
        ]
        verbose_name = 'Invoice'
        verbose_name_plural = 'Invoices'

    def __str__(self):
        return f"{self.invoice_no} - {self.assignment.student} - ₹{self.amount}"


# ---------- Notification Log ----------

class NotificationLog(models.Model):
    assignment = models.ForeignKey(
        StudentFeeAssignment,
        on_delete=models.CASCADE,
        related_name='notification_logs'
    )
    installment = models.ForeignKey(
        FeeInstallment,
        on_delete=models.CASCADE,
        related_name='notification_logs',
        null=True,
        blank=True
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        related_name='notification_logs',
        null=True,
        blank=True
    )
    notification_type = models.CharField(max_length=20, choices=NotificationType.choices, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, db_index=True)
    recipient = models.CharField(max_length=255)  # email or phone
    subject = models.CharField(max_length=255, blank=True)
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_success = models.BooleanField(default=False, db_index=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['assignment', 'notification_type', 'sent_at']),
            models.Index(fields=['channel', 'is_success', 'sent_at']),
        ]
        verbose_name = 'Notification Log'
        verbose_name_plural = 'Notification Logs'

    def __str__(self):
        return f"{self.get_notification_type_display()} → {self.recipient} ({'OK' if self.is_success else 'FAIL'})"


# ---------- Additional Charges ----------

class AdditionalCharge(TrackableMixin, models.Model):
    """A one-off charge on top of the regular fee plan (e.g. uniform,
    late fee, materials) — not generated by FeeStructure/installments."""
    assignment = models.ForeignKey(
        StudentFeeAssignment,
        on_delete=models.CASCADE,
        related_name='additional_charges'
    )
    description = models.CharField(max_length=255)
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    charge_date = models.DateField(default=date.today, db_index=True)
    is_paid = models.BooleanField(default=False, db_index=True)
    paid_on = models.DateField(null=True, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-charge_date']
        verbose_name = 'Additional Charge'
        verbose_name_plural = 'Additional Charges'

    def __str__(self):
        return f"{self.assignment.student} - {self.description} - ₹{self.amount}"


# ---------- Refundable Security Deposit ----------

class DepositPolicy(models.Model):
    """
    The one current Terms & Conditions text for refundable deposits,
    editable by staff via the Django admin rather than hardcoded in code,
    so the school can update wording/notice period without a deploy.
    Treated as a singleton — get_current() creates the first row with a
    sensible default if none exists yet.
    """
    notice_period_days = models.PositiveIntegerField(
        default=30,
        help_text="Default number of days' written notice required before a deposit becomes refundable. "
                   "Can be overridden per deposit."
    )
    terms_text = models.TextField(
        default=(
            "1. The deposit collected at admission is fully refundable when the student "
            "leaves the school, subject to {notice_period} days' written notice being "
            "submitted to the school office in advance.\n\n"
            "2. The refund will be processed within {notice_period} days of the notice "
            "date, after adjusting any outstanding fees, dues, or damages against the "
            "deposit amount.\n\n"
            "3. No deposit will be refunded without prior written notice from the "
            "parent/guardian.\n\n"
            "4. The deposit does not carry any interest for the duration it is held.\n\n"
            "5. In case of damage to school property attributable to the student, the "
            "cost of repair/replacement will be deducted from the deposit before refund."
        ),
        help_text="Use {notice_period} as a placeholder — it is filled in with the value above when displayed."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Deposit Terms & Conditions'
        verbose_name_plural = 'Deposit Terms & Conditions'

    def __str__(self):
        return "Deposit Terms & Conditions"

    @classmethod
    def get_current(cls):
        obj = cls.objects.order_by('-updated_at').first()
        if obj is None:
            obj = cls.objects.create()
        return obj

    @property
    def rendered_terms_text(self):
        return self.terms_text.replace("{notice_period}", str(self.notice_period_days))


class SecurityDeposit(TrackableMixin, models.Model):
    """
    A one-time, refundable deposit collected from a student at admission.
    Separate from StudentFeeAssignment/FeeInstallment — this is not a
    recurring fee, it is held and returned (minus any deductions) when the
    student leaves, after the required notice period.
    """
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='security_deposits'
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    receipt_no = models.CharField(max_length=30, unique=True, editable=False, db_index=True)
    paid_on = models.DateField(default=date.today)
    mode = models.CharField(max_length=20, choices=FeePayment.PAYMENT_MODE_CHOICES, default='cash')
    transaction_ref = models.CharField(max_length=100, blank=True)

    notice_period_days = models.PositiveIntegerField(
        default=30,
        help_text="Days' written notice required before this deposit becomes refundable. "
                   "Pre-filled from the current Deposit Policy at creation, but editable per deposit."
    )
    notice_given_on = models.DateField(
        null=True, blank=True,
        help_text="Date the parent/guardian submitted written notice of leaving."
    )

    is_refunded = models.BooleanField(default=False, db_index=True)
    deduction_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0)],
        help_text="Any amount withheld before refund (damages, outstanding dues, etc.)."
    )
    deduction_reason = models.CharField(max_length=255, blank=True)
    refunded_on = models.DateField(null=True, blank=True)
    refund_mode = models.CharField(max_length=20, choices=FeePayment.PAYMENT_MODE_CHOICES, blank=True)
    refund_transaction_ref = models.CharField(max_length=100, blank=True)

    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-paid_on']
        verbose_name = 'Security Deposit'
        verbose_name_plural = 'Security Deposits'

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            self.receipt_no = f"DEP{timezone.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - Deposit ₹{self.amount} ({'Refunded' if self.is_refunded else 'Held'})"

    @property
    def refund_amount_due(self):
        """What would actually be paid back, after any deductions."""
        if self.is_refunded:
            return Decimal('0.00')
        return max(self.amount - self.deduction_amount, Decimal('0.00'))

    @property
    def expected_refund_date(self):
        if self.notice_given_on:
            return self.notice_given_on + timedelta(days=self.notice_period_days)
        return None

    @property
    def status(self):
        """Held / Notice Given (not yet due) / Ready for Refund / Refunded."""
        if self.is_refunded:
            return "Refunded"
        if self.notice_given_on:
            if date.today() >= self.expected_refund_date:
                return "Ready for Refund"
            return f"Notice Given — refundable from {self.expected_refund_date.strftime('%d %b %Y')}"
        return "Held"
    @property
    def amount_refunded(self):
        """Actual amount paid back to the parent/guardian."""
        if not self.is_refunded:
            return Decimal('0.00')
        return max(self.amount - self.deduction_amount, Decimal('0.00'))

    def record_notice(self, notice_date=None):
        """Parent/guardian has given written notice of leaving."""
        self.notice_given_on = notice_date or date.today()
        self.save()

    def mark_refunded(self, refund_mode='cash', transaction_ref='', refunded_on=None,
                       deduction_amount=None, deduction_reason=''):
        if deduction_amount is not None:
            self.deduction_amount = deduction_amount
        if deduction_reason:
            self.deduction_reason = deduction_reason
        self.is_refunded = True
        self.refunded_on = refunded_on or date.today()
        self.refund_mode = refund_mode
        self.refund_transaction_ref = transaction_ref
        self.save()