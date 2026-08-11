from django.db import models, transaction
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from decimal import Decimal
from datetime import date
from calendar import monthrange
import logging

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


class Channel(models.TextChoices):
    EMAIL = 'email', 'Email'
    SMS = 'sms', 'SMS'
    PUSH = 'push', 'Push Notification'


# ---------- Utility ----------

def add_months(d: date, months: int) -> date:
    """Add months to a date, handling year rollover and month-end."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


# ---------- Models ----------

class FeeCategory(models.Model):
    name = models.CharField(max_length=50, unique=True, db_index=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Fee Category'
        verbose_name_plural = 'Fee Categories'

    def __str__(self):
        return self.name


class FeeStructure(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name='branch_fee_structures'
    )
    class_name = models.ForeignKey(
        'students.Class',
        on_delete=models.CASCADE,
        related_name='class_fee_structures'
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('branch', 'class_name', 'category', 'academic_year')
        ordering = ['branch', 'class_name', 'category']
        indexes = [
            models.Index(fields=['academic_year', 'is_active']),
            models.Index(fields=['branch', 'class_name', 'is_active']),
        ]
        verbose_name = 'Fee Structure'
        verbose_name_plural = 'Fee Structures'

    def __str__(self):
        return f"{self.branch} - {self.class_name} - {self.category} ({self.academic_year})"


class StudentFeeAssignment(models.Model):
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student} - {self.fee_structure.category} - ₹{self.final_amount}"

    # ---------- Installment Generation ----------

    def generate_installments(self):
        """
        Auto-generate installments based on fee structure frequency.
        Uses atomic transaction to ensure consistency.
        """
        frequency = self.fee_structure.frequency
        amount = self.final_amount

        config = {
            Frequency.MONTHLY: (12, 1),
            Frequency.QUARTERLY: (4, 3),
            Frequency.HALF_YEARLY: (2, 6),
            Frequency.YEARLY: (1, 12),
        }
        count, month_step = config.get(frequency, (1, 12))

        if count == 0:
            return

        # Calculate per-installment amount (last one gets remainder to avoid rounding issues)
        base_amount = (amount / count).quantize(Decimal('0.01'))
        total_base = base_amount * count
        remainder = amount - total_base

        # Use assignment-specific start date (Day Care) or fee structure start date (School)
        start_date = self.start_date or self.fee_structure.start_date

        # Prevent duplicate generation
        if self.installments.exists():
            logger.warning(
                "Installments already exist for assignment %s. Skipping generation.",
                self.pk
            )
            return

        installments = []
        for i in range(count):
            due_date = add_months(start_date, month_step * i)
            inst_amount = base_amount + (remainder if i == count - 1 else Decimal('0.00'))

            installments.append(
                FeeInstallment(
                    assignment=self,
                    installment_number=i + 1,
                    amount_due=inst_amount,
                    due_date=due_date,
                )
            )

        FeeInstallment.objects.bulk_create(installments)
        logger.info("Generated %d installments for assignment %s.", count, self.pk)

    @property
    def effective_parent_email(self):
        return self.parent_email or getattr(self.student, 'parent_email', None)

    @property
    def effective_parent_phone(self):
        return self.parent_phone or getattr(self.student, 'parent_phone', None)


class FeeInstallment(models.Model):
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

    @property
    def amount_paid(self):
        return self.payments.aggregate(total=models.Sum('amount_paid'))['total'] or Decimal('0.00')

    @property
    def balance(self):
        return self.amount_due - self.amount_paid

    @property
    def is_overdue(self):
        return not self.is_fully_paid and self.due_date < date.today()

    def __str__(self):
        return f"{self.assignment.student} - Inst {self.installment_number} (Due: {self.due_date})"


class FeePayment(models.Model):
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

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            # Use atomic counter to avoid duplicate receipt numbers under load
            self.receipt_no = f"RCPT{timezone.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"
        super().save(*args, **kwargs)

        # CRITICAL FIX: Toggle is_fully_paid based on ACTUAL balance (both directions)
        # Use update_fields to avoid recursion and unnecessary DB writes
        installment = self.installment
        should_be_paid = installment.balance <= 0
        if installment.is_fully_paid != should_be_paid:
            installment.is_fully_paid = should_be_paid
            installment.save(update_fields=['is_fully_paid'])

    def __str__(self):
        return f"{self.receipt_no} - {self.installment.assignment.student} - ₹{self.amount_paid}"


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
        return f"{self.notification_type.label} → {self.recipient} ({'OK' if self.is_success else 'FAIL'})"