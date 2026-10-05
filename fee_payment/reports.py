"""
Excel (.xlsx) report builders for the fee_payment app.
Requires: pip install openpyxl
"""
from decimal import Decimal
from datetime import date, timedelta

from django.http import HttpResponse
from django.db.models import Sum, Count, Value, DecimalField
from django.db.models.functions import Coalesce, TruncDate, TruncWeek, TruncMonth

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

from .models import FeePayment
from .helpers import get_student_display_id

DEC_FIELD = DecimalField(max_digits=10, decimal_places=2)

PERIOD_TRUNC = {
    'daily': TruncDate,
    'weekly': TruncWeek,
    'monthly': TruncMonth,
}


# ---------- Querysets ----------

def get_collection_report_queryset(period, date_from=None, date_to=None):
    """
    Grouped fee-collection totals for a period ('daily' | 'weekly' | 'monthly'),
    optionally bounded by date_from / date_to (inclusive, on paid_on date).
    """
    trunc_fn = PERIOD_TRUNC.get(period, TruncDate)
    qs = FeePayment.objects.all()
    if date_from:
        qs = qs.filter(paid_on__date__gte=date_from)
    if date_to:
        qs = qs.filter(paid_on__date__lte=date_to)
    return qs.annotate(period=trunc_fn('paid_on')).values('period').annotate(
        total_amount=Coalesce(Sum('amount_paid'), Value(Decimal('0.00')), output_field=DEC_FIELD),
        transaction_count=Count('id'),
    ).order_by('-period')


def default_range_for_period(period):
    """Sensible default date_from/date_to when the user hasn't picked one."""
    today = date.today()
    if period == 'daily':
        return today, today
    if period == 'weekly':
        return today - timedelta(days=today.weekday()), today
    if period == 'monthly':
        return today.replace(day=1), today
    # 'custom' — caller must supply both dates
    return None, None


# ---------- Excel writers ----------

def _style_header(ws, headers, row=1, fill="2E7D32"):
    ws.append(headers)
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=fill, end_color=fill, fill_type="solid")
        cell.alignment = Alignment(horizontal="center")


def _autosize(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _xlsx_response(wb, filename):
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


def export_collection_report_excel(period, date_from, date_to):
    """Summary report: one row per day/week/month with totals."""
    qs = get_collection_report_queryset(period, date_from, date_to)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fee Collection"
    _style_header(ws, ["Period", "Total Amount (Rs.)", "Transaction Count"])

    grand_total = Decimal('0.00')
    grand_count = 0
    for row in qs:
        period_label = row['period'].strftime('%Y-%m-%d') if row['period'] else ''
        ws.append([period_label, float(row['total_amount']), row['transaction_count']])
        grand_total += row['total_amount']
        grand_count += row['transaction_count']

    ws.append([])
    ws.append(["Grand Total", float(grand_total), grand_count])
    for col in range(1, 4):
        ws.cell(row=ws.max_row, column=col).font = Font(bold=True)

    _autosize(ws, [18, 22, 20])
    filename = f"fee_collection_{period}_{date_from}_to_{date_to}.xlsx"
    return _xlsx_response(wb, filename)


def export_payment_ledger_excel(payments_qs, filename="fee_payments.xlsx"):
    """Detailed transaction-level export — every payment row, with running balance."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payments"
    _style_header(ws, [
        "Receipt No", "Student", "Student ID", "Category", "Installment #",
        "Amount Paid (Rs.)", "Mode", "Transaction Ref", "Paid On",
        "Recorded By", "Balance After (Rs.)"
    ], fill="1565C0")

    grand_total = Decimal('0.00')
    for p in payments_qs.select_related(
        'installment__assignment__student',
        'installment__assignment__fee_structure__category',
        'paid_by_staff'
    ):
        student = p.installment.assignment.student
        ws.append([
            p.receipt_no,
            str(student),
            str(get_student_display_id(student)),
            p.installment.assignment.fee_structure.category.name,
            p.installment.installment_number,
            float(p.amount_paid),
            p.get_mode_display(),
            p.transaction_ref,
            p.paid_on.strftime('%Y-%m-%d %H:%M'),
            str(p.paid_by_staff) if p.paid_by_staff else '',
            float(p.installment.balance),
        ])
        grand_total += p.amount_paid

    ws.append([])
    ws.append(["Grand Total", "", "", "", "", float(grand_total)])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.cell(row=ws.max_row, column=6).font = Font(bold=True)

    _autosize(ws, [18, 22, 14, 16, 12, 16, 14, 18, 18, 18, 16])
    return _xlsx_response(wb, filename)


def export_overdue_report_excel(student_summary, filename="overdue_report.xlsx"):
    """
    student_summary: iterable of dicts like
    {'student': <Student>, 'student_display_id': ..., 'installment_count': int, 'total_overdue': Decimal}
    (matches the shape already built in views.SendDueRemindersView / FeeDueSearchView)
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Overdue Fees"
    _style_header(ws, ["Student", "Student ID", "Pending Installments", "Total Overdue (Rs.)"], fill="C62828")

    grand_total = Decimal('0.00')
    for row in student_summary:
        ws.append([
            str(row['student']) if row['student'] else 'Unknown',
            str(row['student_display_id']),
            row['installment_count'],
            float(row['total_overdue']),
        ])
        grand_total += row['total_overdue']

    ws.append([])
    ws.append(["Grand Total", "", "", float(grand_total)])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)

    _autosize(ws, [24, 16, 20, 18])
    return _xlsx_response(wb, filename)
