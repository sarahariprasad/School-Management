"""
Notification utilities for the fee payment system.

Design principles:
1. Fail-safe: Notification failures are caught and logged; they NEVER break the main transaction.
2. Channel-agnostic: Easy to add SMS, WhatsApp, Push later.
3. Audit trail: Every attempt is persisted in NotificationLog.
4. Idempotency: Same notification type + installment within 24h is skipped (optional guard).

Dependencies:
    - Django core mail (configured EMAIL_BACKEND)
    - (Optional) twilio for SMS
    - (Optional) django-push-notifications for push
"""

import logging
from typing import Optional
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta

from .models import (
    FeePayment, FeeInstallment, StudentFeeAssignment,
    NotificationLog, NotificationType, Channel
)

logger = logging.getLogger(__name__)


# ---------- Low-level Channel Backends ----------

def send_email(
    recipient: str,
    subject: str,
    message: str,
    html_message: Optional[str] = None
) -> bool:
    """Send email via Django's mail backend. Returns True on success."""
    if not recipient:
        logger.warning("Email skipped: no recipient provided.")
        return False

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@school.edu'),
            recipient_list=[recipient],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.exception("Email send failed to %s: %s", recipient, e)
        return False


def send_sms(phone: str, message: str) -> bool:
    """
    SMS backend placeholder.
    Integrate Twilio / Exotel / AWS SNS here.
    """
    if not phone:
        logger.warning("SMS skipped: no phone number provided.")
        return False

    # Example Twilio integration (uncomment when ready):
    # from twilio.rest import Client
    # client = Client(settings.TWILIO_SID, settings.TWILIO_TOKEN)
    # client.messages.create(body=message, from_=settings.TWILIO_PHONE, to=phone)

    logger.info("SMS placeholder: to=%s | msg=%s", phone, message[:60])
    return True


# ---------- Core Notification Dispatcher ----------

def dispatch_notification(
    assignment: StudentFeeAssignment,
    notification_type: str,
    subject: str,
    message: str,
    html_message: Optional[str] = None,
    installment: Optional[FeeInstallment] = None,
    channels: Optional[list] = None
) -> dict:
    """
    Dispatch notification across configured channels.
    Returns dict with per-channel success status.
    """
    if channels is None:
        channels = [Channel.EMAIL]  # Default channel

    if not assignment.notify_parent:
        logger.info("Notification skipped: notify_parent=False for assignment %s", assignment.pk)
        return {}

    results = {}
    email = assignment.effective_parent_email
    phone = assignment.effective_parent_phone

    for channel in channels:
        success = False
        error_msg = ""
        recipient = ""

        try:
            if channel == Channel.EMAIL:
                recipient = email or ""
                success = send_email(recipient, subject, message, html_message)
            elif channel == Channel.SMS:
                recipient = phone or ""
                success = send_sms(recipient, message)
            else:
                error_msg = f"Unknown channel: {channel}"
        except Exception as e:
            error_msg = str(e)
            logger.exception("Channel %s failed: %s", channel, e)

        # Persist log
        NotificationLog.objects.create(
            assignment=assignment,
            installment=installment,
            notification_type=notification_type,
            channel=channel,
            recipient=recipient,
            subject=subject,
            message=message,
            is_success=success,
            error_message=error_msg
        )

        results[channel] = success

    return results


# ---------- High-level Notification Helpers ----------

def send_fee_due_notification(assignment: StudentFeeAssignment) -> bool:
    """
    Send fee due notification when installments are first generated.
    Called typically from a signal after assignment creation.
    """
    student_name = getattr(assignment.student, 'name', 'Student')
    category = assignment.fee_structure.category.name
    academic_year = assignment.fee_structure.academic_year
    total = assignment.final_amount

    subject = f"Fee Due: {category} ({academic_year})"
    message = (
        f"Dear Parent/Guardian,\n\n"
        f"Fee has been assigned for {student_name} under {category} "
        f"for academic year {academic_year}.\n"
        f"Total Amount Due: ₹{total}\n"
        f"Frequency: {assignment.fee_structure.get_frequency_display()}\n\n"
        f"Please clear the dues before the respective due dates.\n\n"
        f"Regards,\nSchool Finance Office"
    )

    results = dispatch_notification(
        assignment=assignment,
        notification_type=NotificationType.FEE_DUE,
        subject=subject,
        message=message,
        channels=[Channel.EMAIL, Channel.SMS]
    )
    return any(results.values())


def send_payment_recorded_notification(payment: FeePayment) -> bool:
    """
    Send payment confirmation to parent when a payment is recorded.
    Called from FeePaymentCreateView (non-blocking).
    """
    assignment = payment.installment.assignment
    student_name = getattr(assignment.student, 'name', 'Student')
    receipt_no = payment.receipt_no
    amount = payment.amount_paid
    mode = payment.get_mode_display()
    installment_no = payment.installment.installment_number
    balance = payment.installment.balance

    subject = f"Payment Received - Receipt {receipt_no}"
    message = (
        f"Dear Parent/Guardian,\n\n"
        f"We have received a payment for {student_name}.\n\n"
        f"Receipt No: {receipt_no}\n"
        f"Amount Paid: ₹{amount}\n"
        f"Payment Mode: {mode}\n"
        f"Installment: #{installment_no}\n"
        f"Remaining Balance: ₹{balance}\n\n"
        f"Thank you.\n"
        f"Regards,\nSchool Finance Office"
    )

    results = dispatch_notification(
        assignment=assignment,
        notification_type=NotificationType.PAYMENT_RECORDED,
        subject=subject,
        message=message,
        installment=payment.installment,
        channels=[Channel.EMAIL, Channel.SMS]
    )
    return any(results.values())


def send_due_reminder_notification(installment: FeeInstallment) -> bool:
    """
    Send due reminder for a specific installment.
    Guard: Skip if already sent within last 24 hours.
    """
    assignment = installment.assignment
    student_name = getattr(assignment.student, 'name', 'Student')
    category = assignment.fee_structure.category.name
    due_date = installment.due_date
    balance = installment.balance
    installment_no = installment.installment_number

    # Idempotency guard: skip if reminder sent in last 24h
    recent_log = NotificationLog.objects.filter(
        assignment=assignment,
        installment=installment,
        notification_type=NotificationType.DUE_REMINDER,
        sent_at__gte=timezone.now() - timedelta(hours=24)
    ).exists()

    if recent_log:
        logger.info("Skipping duplicate reminder for installment %s", installment.pk)
        return True  # Treat as success (already handled)

    subject = f"Reminder: Fee Due for {student_name}"
    message = (
        f"Dear Parent/Guardian,\n\n"
        f"This is a gentle reminder that fee installment #{installment_no} "
        f"for {student_name} under {category} is pending.\n"
        f"Due Date: {due_date}\n"
        f"Balance Amount: ₹{balance}\n\n"
        f"Please make the payment at the earliest to avoid late charges.\n\n"
        f"Regards,\nSchool Finance Office"
    )

    results = dispatch_notification(
        assignment=assignment,
        notification_type=NotificationType.DUE_REMINDER,
        subject=subject,
        message=message,
        installment=installment,
        channels=[Channel.EMAIL, Channel.SMS]
    )
    return any(results.values())


def send_overdue_notification(installment: FeeInstallment) -> bool:
    """Send overdue notice for installments past due date."""
    assignment = installment.assignment
    student_name = getattr(assignment.student, 'name', 'Student')
    category = assignment.fee_structure.category.name
    due_date = installment.due_date
    balance = installment.balance
    days_overdue = (timezone.now().date() - due_date).days

    subject = f"URGENT: Overdue Fee for {student_name}"
    message = (
        f"Dear Parent/Guardian,\n\n"
        f"Fee installment for {student_name} under {category} is OVERDUE by {days_overdue} day(s).\n"
        f"Due Date: {due_date}\n"
        f"Outstanding Balance: ₹{balance}\n\n"
        f"Please clear the dues immediately to avoid any penalties or service restrictions.\n\n"
        f"Regards,\nSchool Finance Office"
    )

    results = dispatch_notification(
        assignment=assignment,
        notification_type=NotificationType.OVERDUE,
        subject=subject,
        message=message,
        installment=installment,
        channels=[Channel.EMAIL, Channel.SMS]
    )
    return any(results.values())