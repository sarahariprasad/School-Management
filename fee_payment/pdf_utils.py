"""
fee_payment/pdf_utils.py

Generates invoice and payment-receipt PDFs as in-memory bytes, used both
for emailing (as attachments) and for the existing InvoicePDFDownloadView.

Layout follows the school's existing receipt format (name, father's name,
ERP ID, class/section, a fee-particulars table, amount in words, and the
remaining balance), with the receipt split into School Copy + Student Copy
on one page the same way the reference receipt does.

Deliberately takes plain objects (duck-typed) rather than importing
Invoice/FeePayment from .models, so this module has no risk of circular
imports with models.py (which calls into here).

Requires: pip install reportlab
"""

import io
import textwrap
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas


SCHOOL_NAME = "NOWMI CGC"


def _format_print_date(dt=None):
    """
    Portable equivalent of strftime('%B %-d, %Y, %-I:%M:%S %p') — the '-'
    no-leading-zero flag is Linux/Mac only and raises ValueError on Windows.
    """
    dt = dt or datetime.now()
    hour12 = dt.strftime('%I').lstrip('0') or '12'
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}, {hour12}:{dt.strftime('%M:%S %p')}"


# ---------- Amount-in-words (Indian numbering: crore / lakh / thousand) ----------

_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
    "Eighteen", "Nineteen"
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digit_words(n):
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _three_digit_words(n):
    hundred, rest = divmod(n, 100)
    parts = []
    if hundred:
        parts.append(f"{_ONES[hundred]} Hundred")
    if rest:
        parts.append(_two_digit_words(rest))
    return " ".join(parts)


def amount_in_words(amount) -> str:
    """e.g. 32000 -> 'Thirty Two Thousand Rupees Only' (Indian numbering)."""
    try:
        n = int(round(float(amount)))
    except (TypeError, ValueError):
        return ""
    if n == 0:
        return "Zero Rupees Only"

    crore, n = divmod(n, 10000000)
    lakh, n = divmod(n, 100000)
    thousand, rest = divmod(n, 1000)

    parts = []
    if crore:
        parts.append(f"{_two_digit_words(crore)} Crore")
    if lakh:
        parts.append(f"{_two_digit_words(lakh)} Lakh")
    if thousand:
        parts.append(f"{_two_digit_words(thousand)} Thousand")
    if rest:
        parts.append(_three_digit_words(rest))
    return " ".join(parts) + " Rupees Only"


# ---------- Small helpers ----------

def _safe(value, default="-"):
    if value is None or value == "":
        return default
    return str(value)


def _get_erp_id(student):
    try:
        from .helpers import get_student_display_id
        return get_student_display_id(student)
    except Exception:
        return _safe(getattr(student, "student_id", None))


def _get_class_section(student):
    group = getattr(student, "group", None)
    branch = getattr(student, "student_branch", None)
    class_label = getattr(group, "name", None) if group else None
    section_label = str(branch) if branch else None
    return _safe(class_label), _safe(section_label)


def _draw_kv(c, x, y, label, value, value_x):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x, y, label)
    c.setFont("Helvetica", 9)
    c.drawString(value_x, y, _safe(value))


def _draw_paragraph(c, x, y, text, width_chars=100, font="Helvetica", size=9, leading=4.8 * mm):
    """Wraps plain text to fit and draws it line by line. Returns the y
    position after the last line, for chaining further content below it."""
    c.setFont(font, size)
    for line in textwrap.wrap(text, width_chars):
        c.drawString(x, y, line)
        y -= leading
    return y


def _draw_table(c, x, y_top, col_widths, rows, row_height=6.5 * mm):
    """Draws a bordered table. rows[0] is treated as the header row.
    Column 0 is left-aligned; other columns are right-aligned (numbers)."""
    total_width = sum(col_widths)
    n_rows = len(rows)

    c.setLineWidth(0.4)
    c.setStrokeColor(colors.black)

    for i in range(n_rows + 1):
        yy = y_top - i * row_height
        c.line(x, yy, x + total_width, yy)

    xx = x
    c.line(xx, y_top, xx, y_top - n_rows * row_height)
    for w in col_widths:
        xx += w
        c.line(xx, y_top, xx, y_top - n_rows * row_height)

    for ri, row in enumerate(rows):
        yy = y_top - ri * row_height - row_height + 2.2 * mm
        xx = x
        for ci, cell in enumerate(row):
            c.setFont("Helvetica-Bold" if ri == 0 else "Helvetica", 9)
            if ci == 0:
                c.drawString(xx + 2 * mm, yy, str(cell))
            else:
                c.drawRightString(xx + col_widths[ci] - 2 * mm, yy, str(cell))
            xx += col_widths[ci]

    return y_top - n_rows * row_height


# ---------- Receipt (two copies per page: School Copy + Student Copy) ----------

def _draw_receipt_copy(c, x0, y0, box_width, box_height, payment, copy_label):
    installment = payment.installment
    assignment = installment.assignment
    student = assignment.student

    erp_id = _get_erp_id(student)
    class_label, section_label = _get_class_section(student)
    words = amount_in_words(payment.amount_paid)

    top = y0 + box_height

    c.setFont("Helvetica-Bold", 13)
    c.drawString(x0, top - 6 * mm, SCHOOL_NAME)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x0 + box_width, top - 6 * mm, "PAYMENT RECEIPT")

    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(x0, top - 9 * mm, x0 + box_width, top - 9 * mm)

    right_x = x0 + box_width * 0.58
    y = top - 15 * mm
    _draw_kv(c, x0, y, "Student's Name :", student.name, x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Payment Date:", payment.paid_on.strftime('%Y-%m-%d'), right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "Father's Name :", getattr(student, "father_name", None), x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Receipt No:", payment.receipt_no, right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "ERP Id :", erp_id, x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Class :", f"{class_label} | {section_label}", right_x + 28 * mm)
    y -= 9 * mm

    col_widths = [box_width - 70 * mm, 35 * mm, 35 * mm]
    rows = [
        ["Fee Particulars", "Amount", "Installment Due"],
        [
            f"{assignment.fee_structure.category.name} - Installment {installment.installment_number}",
            f"{payment.amount_paid}",
            f"{installment.balance}",
        ],
        [
            f"Total ({words})",
            f"{payment.amount_paid}",
            f"{installment.balance}",
        ],
    ]
    y = _draw_table(c, x0, y, col_widths, rows)
    y -= 6 * mm

    c.setFont("Helvetica-Bold", 9)
    c.drawString(x0, y, "Total Tuition Fee Due")
    c.drawRightString(x0 + box_width, y, f"{assignment.total_balance}")
    y -= 6 * mm

    c.setFont("Helvetica", 9)
    c.drawString(x0, y, f"Payment Mode: {payment.get_mode_display()}")

    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x0 + box_width / 2, y0 + 3 * mm, copy_label)
    c.setFont("Helvetica-Oblique", 7)
    c.drawRightString(
        x0 + box_width, y0 + 3 * mm,
        f"Print Date: {_format_print_date()}"
    )


def generate_receipt_pdf(payment) -> bytes:
    """payment: fee_payment.models.FeePayment instance."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    margin = 15 * mm
    box_width = width - 2 * margin
    gap = 10 * mm
    box_height = (height - 2 * margin - gap) / 2

    top_box_y = margin + box_height + gap
    bottom_box_y = margin

    _draw_receipt_copy(c, margin, top_box_y, box_width, box_height, payment, "School Copy")

    cut_y = top_box_y - gap / 2
    c.setDash(3, 3)
    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(margin, cut_y, margin + box_width, cut_y)
    c.setDash()

    _draw_receipt_copy(c, margin, bottom_box_y, box_width, box_height, payment, "Student Copy")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


# ---------- Security Deposit ----------

def generate_deposit_receipt_pdf(deposit) -> bytes:
    """deposit: fee_payment.models.SecurityDeposit instance."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    student = deposit.student

    erp_id = _get_erp_id(student)
    class_label, section_label = _get_class_section(student)
    words = amount_in_words(deposit.amount)

    x0, top = 20 * mm, height - 20 * mm
    box_width = width - 2 * x0

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x0, top, SCHOOL_NAME)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(x0 + box_width, top, "SECURITY DEPOSIT RECEIPT")

    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(x0, top - 6 * mm, x0 + box_width, top - 6 * mm)

    right_x = x0 + box_width * 0.58
    y = top - 14 * mm
    _draw_kv(c, x0, y, "Student's Name :", student.name, x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Receipt No:", deposit.receipt_no, right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "Father's Name :", getattr(student, "father_name", None), x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Paid On:", deposit.paid_on.strftime('%Y-%m-%d'), right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "ERP Id :", erp_id, x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Payment Mode:", deposit.get_mode_display(), right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "Class :", f"{class_label} | {section_label}", x0 + 32 * mm)
    y -= 10 * mm

    col_widths = [box_width - 45 * mm, 45 * mm]
    rows = [
        ["Particulars", "Amount"],
        ["Refundable Security Deposit", f"{deposit.amount}"],
        [f"Total ({words})", f"{deposit.amount}"],
    ]
    y = _draw_table(c, x0, y, col_widths, rows)
    y -= 8 * mm

    y = _draw_paragraph(
        c, x0, y,
        f"This deposit is refundable in full upon the student leaving the school, provided at "
        f"least {deposit.notice_period_days} days' written notice is given and all dues are "
        f"cleared. See the attached Terms & Conditions for full details.",
        width_chars=100
    )

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(x0, 15 * mm, "This is a system-generated receipt.")
    c.drawRightString(x0 + box_width, 15 * mm, f"Print Date: {_format_print_date()}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def generate_deposit_refund_pdf(deposit) -> bytes:
    """deposit: fee_payment.models.SecurityDeposit instance, already refunded."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    student = deposit.student
    erp_id = _get_erp_id(student)
    words = amount_in_words(deposit.refund_amount or 0)

    x0, top = 20 * mm, height - 20 * mm
    box_width = width - 2 * x0

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x0, top, SCHOOL_NAME)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(x0 + box_width, top, "DEPOSIT REFUND RECEIPT")

    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(x0, top - 6 * mm, x0 + box_width, top - 6 * mm)

    right_x = x0 + box_width * 0.58
    y = top - 14 * mm
    _draw_kv(c, x0, y, "Student's Name :", student.name, x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Original Receipt:", deposit.receipt_no, right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "ERP Id :", erp_id, x0 + 32 * mm)
    refunded_str = deposit.refunded_on.strftime('%Y-%m-%d') if deposit.refunded_on else "-"
    _draw_kv(c, right_x, y, "Refunded On:", refunded_str, right_x + 28 * mm)
    y -= 10 * mm

    col_widths = [box_width - 45 * mm, 45 * mm]
    rows = [
        ["Particulars", "Amount"],
        ["Original Deposit", f"{deposit.amount}"],
        [f"Deductions ({deposit.deduction_reason or 'None'})", f"{deposit.deduction_amount}"],
        [f"Refund Amount ({words})", f"{deposit.refund_amount}"],
    ]
    y = _draw_table(c, x0, y, col_widths, rows)
    y -= 8 * mm

    if deposit.refund_remarks:
        c.setFont("Helvetica", 9)
        c.drawString(x0, y, f"Remarks: {deposit.refund_remarks}")

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(x0, 15 * mm, "This is a system-generated refund receipt.")
    c.drawRightString(x0 + box_width, 15 * mm, f"Print Date: {_format_print_date()}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


_DEPOSIT_TERMS_CLAUSES = [
    ("1. Nature of the Deposit",
     "The security deposit collected at admission is a refundable deposit, not a fee. It is "
     "held by the school as security against unpaid dues or damage to school property, and is "
     "not adjusted against regular tuition or other fees during the student's enrolment."),
    ("2. Notice Period",
     "A guardian wishing to withdraw the student from the school must give the school at least "
     "{notice_days} days' written notice. The refund becomes due only after this notice period "
     "has elapsed."),
    ("3. Refund Process",
     "Once the notice period has elapsed and all outstanding fees, if any, have been cleared, "
     "the deposit — less any applicable deductions — will be refunded to the guardian."),
    ("4. Deductions",
     "The school may deduct from the deposit any amount owed for unpaid fees, damage to school "
     "property, or unreturned school materials (books, uniforms, ID cards, etc.). Any such "
     "deduction will be itemised and communicated to the guardian in writing at the time of "
     "refund."),
    ("5. Withdrawal Without Full Notice",
     "If a student is withdrawn without the required notice period being served in full, the "
     "refund will still be processed, but only after a period equivalent to the required notice "
     "has passed from the date the school is informed of the withdrawal."),
    ("6. Non-Transferability",
     "The deposit is specific to the student for whom it was paid. It cannot be transferred to "
     "another student or adjusted against another family's account."),
]


def generate_deposit_terms_pdf(student=None, notice_period_days=30) -> bytes:
    """
    Standalone Terms & Conditions document for the security deposit policy.
    Personalised with the student's name/ERP ID when one is given; otherwise
    a generic copy. NOTE: the clause text below is a reasonable starting
    template, not legal advice — have it reviewed against the school's
    actual policy before relying on it.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    x0 = 20 * mm
    box_width = width - 2 * x0
    y = height - 20 * mm

    c.setFont("Helvetica-Bold", 15)
    c.drawString(x0, y, SCHOOL_NAME)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x0 + box_width, y, "SECURITY DEPOSIT — TERMS & CONDITIONS")
    y -= 7 * mm
    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(x0, y, x0 + box_width, y)
    y -= 10 * mm

    if student is not None:
        c.setFont("Helvetica", 10)
        c.drawString(x0, y, f"Issued to: {student.name}  (ERP ID: {_get_erp_id(student)})")
        y -= 10 * mm

    for title, body in _DEPOSIT_TERMS_CLAUSES:
        if y < 35 * mm:
            c.showPage()
            y = height - 20 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x0, y, title)
        y -= 6 * mm
        y = _draw_paragraph(c, x0, y, body.format(notice_days=notice_period_days), width_chars=100)
        y -= 5 * mm

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        x0, 15 * mm,
        "This document is a general summary; the school's official policy governs in case of any conflict."
    )
    c.drawRightString(x0 + box_width, 15 * mm, f"Print Date: {_format_print_date()}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


# ---------- Security Deposit ----------

def _draw_wrapped_text(c, x, y, text, max_width_mm, font="Helvetica", size=9, leading=5 * mm):
    """Simple word-wrap for a block of text, paragraph by paragraph (split
    on blank lines, as DepositPolicy.terms_text uses them as separators)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    max_width = max_width_mm
    c.setFont(font, size)
    for paragraph in text.split("\n\n"):
        words = paragraph.replace("\n", " ").split()
        line = ""
        for word in words:
            trial = f"{line} {word}".strip()
            if stringWidth(trial, font, size) <= max_width:
                line = trial
            else:
                c.drawString(x, y, line)
                y -= leading
                line = word
        if line:
            c.drawString(x, y, line)
            y -= leading
        y -= leading * 0.6  # paragraph gap
    return y


def generate_deposit_receipt_pdf(deposit) -> bytes:
    """deposit: fee_payment.models.SecurityDeposit instance."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    student = deposit.student

    erp_id = _get_erp_id(student)
    class_label, section_label = _get_class_section(student)
    words = amount_in_words(deposit.amount)

    x0, top = 20 * mm, height - 20 * mm
    box_width = width - 2 * x0

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x0, top, SCHOOL_NAME)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(x0 + box_width, top, "SECURITY DEPOSIT RECEIPT")

    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(x0, top - 6 * mm, x0 + box_width, top - 6 * mm)

    right_x = x0 + box_width * 0.58
    y = top - 14 * mm
    _draw_kv(c, x0, y, "Student's Name :", student.name, x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Receipt No:", deposit.receipt_no, right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "Father's Name :", getattr(student, "father_name", None), x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Paid On:", deposit.paid_on.strftime('%Y-%m-%d'), right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "ERP Id :", erp_id, x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Payment Mode:", deposit.get_mode_display(), right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "Class :", f"{class_label} | {section_label}", x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Notice Period:", f"{deposit.notice_period_days} days", right_x + 28 * mm)
    y -= 10 * mm

    col_widths = [box_width - 45 * mm, 45 * mm]
    rows = [
        ["Particulars", "Amount"],
        ["Refundable Security Deposit", f"{deposit.amount}"],
        [f"Total ({words})", f"{deposit.amount}"],
    ]
    y = _draw_table(c, x0, y, col_widths, rows)
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0, y, "This deposit is fully refundable on leaving the school,")
    y -= 5 * mm
    c.drawString(x0, y, f"subject to {deposit.notice_period_days} days' written notice.")
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    c.drawString(x0, y, "Full terms & conditions are available on request or via the student portal.")
    y -= 10 * mm

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(x0, 15 * mm, "This is a system-generated receipt. Please retain it for your records.")
    c.drawRightString(x0 + box_width, 15 * mm, f"Print Date: {_format_print_date()}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def generate_deposit_terms_pdf(policy=None) -> bytes:
    """
    policy: fee_payment.models.DepositPolicy instance. If omitted, callers
    should pass DepositPolicy.get_current() — kept optional here only so
    this module never needs to import models.py at the top level.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    x0, top = 20 * mm, height - 20 * mm
    box_width = width - 2 * x0

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x0, top, SCHOOL_NAME)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(x0 + box_width, top, "SECURITY DEPOSIT")
    c.setFont("Helvetica", 11)
    c.drawRightString(x0 + box_width, top - 6 * mm, "Terms & Conditions")

    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(x0, top - 10 * mm, x0 + box_width, top - 10 * mm)

    text = policy.rendered_terms_text if policy else (
        "Please contact the school office for current deposit terms and conditions."
    )
    y = top - 20 * mm
    y = _draw_wrapped_text(c, x0, y, text, max_width_mm=box_width, font="Helvetica", size=10, leading=5.5 * mm)

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(x0, 15 * mm, "This document is system-generated and reflects the policy at the time of download.")
    c.drawRightString(x0 + box_width, 15 * mm, f"Print Date: {_format_print_date()}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


# ---------- Invoice ----------

def generate_invoice_pdf(invoice) -> bytes:
    """invoice: fee_payment.models.Invoice instance."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    assignment = invoice.assignment
    student = assignment.student

    erp_id = _get_erp_id(student)
    class_label, section_label = _get_class_section(student)
    words = amount_in_words(invoice.amount)

    x0, top = 20 * mm, height - 20 * mm
    box_width = width - 2 * x0

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x0, top, SCHOOL_NAME)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(x0 + box_width, top, "INVOICE")

    c.setStrokeColor(colors.HexColor("#999999"))
    c.line(x0, top - 6 * mm, x0 + box_width, top - 6 * mm)

    right_x = x0 + box_width * 0.58
    y = top - 14 * mm
    _draw_kv(c, x0, y, "Student's Name :", student.name, x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Invoice No:", invoice.invoice_no, right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "Father's Name :", getattr(student, "father_name", None), x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Invoice Date:", invoice.invoice_date.strftime('%Y-%m-%d'), right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "ERP Id :", erp_id, x0 + 32 * mm)
    due_date = invoice.installment.due_date.strftime('%Y-%m-%d') if invoice.installment else "-"
    _draw_kv(c, right_x, y, "Due Date:", due_date, right_x + 28 * mm)
    y -= 6 * mm
    _draw_kv(c, x0, y, "Class :", f"{class_label} | {section_label}", x0 + 32 * mm)
    _draw_kv(c, right_x, y, "Status:", invoice.get_status_display(), right_x + 28 * mm)
    y -= 10 * mm

    col_widths = [box_width - 45 * mm, 45 * mm]
    desc = f"{assignment.fee_structure.category.name} ({assignment.fee_structure.academic_year})"
    if invoice.installment:
        desc += f" - Installment {invoice.installment.installment_number}"
    rows = [
        ["Fee Particulars", "Amount"],
        [desc, f"{invoice.amount}"],
        [f"Total ({words})", f"{invoice.amount}"],
    ]
    y = _draw_table(c, x0, y, col_widths, rows)
    y -= 10 * mm

    if invoice.remarks:
        c.setFont("Helvetica", 9)
        c.drawString(x0, y, f"Remarks: {invoice.remarks}")
        y -= 8 * mm

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(x0, 15 * mm, "This is a system-generated invoice.")
    c.drawRightString(
        x0 + box_width, 15 * mm,
        f"Print Date: {_format_print_date()}"
    )

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()