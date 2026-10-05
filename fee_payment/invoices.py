"""
fee_payment/invoices.py

Invoice creation and email delivery. Referenced from views.py as
`from . import invoices as invoice_utils`.
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Invoice, InvoiceStatus, NotificationType, Channel, NotificationLog
from .pdf_utils import generate_invoice_pdf

logger = logging.getLogger(__name__)


def _next_invoice_no():
    """
    Sequential number scoped to today, e.g. INV20260924-0001. Recomputed
    from the DB each call rather than cached, so it stays correct even if
    invoices are created from multiple places.
    """
    today_str = timezone.now().strftime('%Y%m%d')
    prefix = f"INV{today_str}-"
    last = (
        Invoice.objects.filter(invoice_no__startswith=prefix)
        .order_by('-invoice_no')
        .values_list('invoice_no', flat=True)
        .first()
    )
    if last:
        last_seq = int(last.rsplit('-', 1)[-1])
    else:
        last_seq = 0
    return f"{prefix}{last_seq + 1:04d}"


def create_invoice(assignment, installment=None, user=None):
    """
    Create and persist an Invoice for a fee assignment, optionally scoped to
    a single installment. Amount defaults to the installment's amount_due
    when given, otherwise the assignment's outstanding total_balance.

    Also generates the invoice PDF immediately and saves it onto
    invoice.pdf_file, so:
      - InvoicePDFDownloadView has something to serve right away
      - send_invoice_email() can attach the same stored PDF rather than
        regenerating it
    """
    if installment is not None:
        amount = installment.amount_due
    else:
        amount = assignment.total_balance
        if amount <= 0:
            amount = assignment.final_amount

    invoice = Invoice.objects.create(
        assignment=assignment,
        installment=installment,
        invoice_no=_next_invoice_no(),
        invoice_date=timezone.now().date(),
        amount=amount,
        status=InvoiceStatus.GENERATED,
        created_by=user,
        updated_by=user,
    )

    try:
        pdf_bytes = generate_invoice_pdf(invoice)
        invoice.pdf_file.save(f"{invoice.invoice_no}.pdf", ContentFile(pdf_bytes), save=True)
    except Exception as e:
        # Invoice record itself is still valid without a PDF — don't let a
        # rendering bug block invoice creation. send_invoice_email() falls
        # back to generating the PDF on the fly if pdf_file is empty.
        logger.exception("Failed to render PDF for invoice %s: %s", invoice.invoice_no, e)

    logger.info(
        "Created invoice %s for assignment %s (installment=%s) amount=₹%s",
        invoice.invoice_no, assignment.pk, installment.pk if installment else None, amount
    )
    return invoice


def send_invoice_email(invoice):
    """
    Email the invoice to the parent on file, with the invoice PDF attached.
    Returns True on success, False on failure. Every attempt (success or
    failure) is written to NotificationLog either way.
    """
    assignment = invoice.assignment
    recipient = assignment.effective_parent_email

    if not recipient:
        logger.warning("Invoice %s has no parent email to send to.", invoice.invoice_no)
        NotificationLog.objects.create(
            assignment=assignment,
            installment=invoice.installment,
            invoice=invoice,
            notification_type=NotificationType.INVOICE_SENT,
            channel=Channel.EMAIL,
            recipient="(none on file)",
            subject=f"Invoice {invoice.invoice_no}",
            message="No parent email on file — invoice not sent.",
            is_success=False,
            error_message="No recipient email available.",
        )
        return False

    subject = f"Invoice {invoice.invoice_no} — {assignment.student.name}"
    body = (
        f"Dear Parent/Guardian,\n\n"
        f"Please find attached the invoice for {assignment.student.name} "
        f"({assignment.fee_structure.category}).\n\n"
        f"Invoice No: {invoice.invoice_no}\n"
        f"Invoice Date: {invoice.invoice_date.strftime('%d %b %Y')}\n"
        f"Amount: ₹{invoice.amount}\n\n"
        f"Thank you.\n"
    )

    # Prefer the already-saved PDF (from create_invoice); regenerate only if
    # it's somehow missing (e.g. that initial render failed).
    try:
        if invoice.pdf_file:
            invoice.pdf_file.open('rb')
            pdf_bytes = invoice.pdf_file.read()
            invoice.pdf_file.close()
        else:
            pdf_bytes = generate_invoice_pdf(invoice)
    except Exception as e:
        logger.exception("Could not obtain PDF for invoice %s, regenerating: %s", invoice.invoice_no, e)
        pdf_bytes = generate_invoice_pdf(invoice)

    try:
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            to=[recipient],
        )
        email.attach(f"{invoice.invoice_no}.pdf", pdf_bytes, 'application/pdf')
        email.send(fail_silently=False)

        invoice.status = InvoiceStatus.SENT
        invoice.sent_at = timezone.now()
        invoice.save(update_fields=['status', 'sent_at'])

        NotificationLog.objects.create(
            assignment=assignment,
            installment=invoice.installment,
            invoice=invoice,
            notification_type=NotificationType.INVOICE_SENT,
            channel=Channel.EMAIL,
            recipient=recipient,
            subject=subject,
            message=body,
            is_success=True,
        )
        logger.info("Invoice %s emailed to %s with PDF attached.", invoice.invoice_no, recipient)
        return True

    except Exception as e:
        logger.exception("Failed to email invoice %s: %s", invoice.invoice_no, e)
        NotificationLog.objects.create(
            assignment=assignment,
            installment=invoice.installment,
            invoice=invoice,
            notification_type=NotificationType.INVOICE_SENT,
            channel=Channel.EMAIL,
            recipient=recipient,
            subject=subject,
            message=body,
            is_success=False,
            error_message=str(e),
        )
        return False