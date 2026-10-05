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