from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from core.permissions import role_required
from .forms import BranchForm
from .models import Branch


@login_required
def branch_list(request):
    """List branches based on user role and permissions."""
    if request.user.is_system_admin:
        branches_qs = Branch.objects.all()
    else:
        allowed_ids = list(request.user.accessible_branches.values_list("id", flat=True))
        if request.user.branch_id:
            allowed_ids.append(request.user.branch_id)
        branches_qs = Branch.objects.filter(pk__in=allowed_ids).distinct()

    paginator = Paginator(branches_qs.order_by("name"), 15)
    page_number = request.GET.get("page")
    branches = paginator.get_page(page_number)

    return render(request, "branches/list.html", {
        "branches": branches,
        "total_count": paginator.count,
    })


@login_required
@role_required("SYSTEM_ADMIN")
def branch_create(request):
    form = BranchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        branch = form.save()
        messages.success(request, f'Branch "{branch.name}" created successfully.')
        return redirect("branch_list")
    return render(request, "branches/form.html", {
        "form": form,
        "title": "Add Branch",
        "action": "Create",
    })


@login_required
@role_required("SYSTEM_ADMIN")
def branch_edit(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    form = BranchForm(request.POST or None, instance=branch)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f'Branch "{branch.name}" updated successfully.')
        return redirect("branch_list")
    return render(request, "branches/form.html", {
        "form": form,
        "title": "Edit Branch",
        "action": "Update",
        "branch": branch,
    })


@login_required
@role_required("SYSTEM_ADMIN")
def branch_delete(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == "POST":
        name = branch.name
        branch.delete()
        messages.success(request, f'Branch "{name}" deleted successfully.')
        return redirect("branch_list")
    return render(request, "branches/confirm_delete.html", {
        "branch": branch,
    })


@login_required
def branch_export_excel(request):
    """Export all branches to an Excel (.xlsx) file."""
    if request.user.is_system_admin:
        branches_qs = Branch.objects.all().order_by("name")
    else:
        allowed_ids = list(request.user.accessible_branches.values_list("id", flat=True))
        if request.user.branch_id:
            allowed_ids.append(request.user.branch_id)
        branches_qs = Branch.objects.filter(pk__in=allowed_ids).distinct().order_by("name")

    wb = Workbook()
    ws = wb.active
    ws.title = "Branches"

    # Styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="0d6efd", end_color="0d6efd", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    # Headers
    headers = ["#", "Branch Code", "Branch Name", "Address", "Phone", "Email", "Status", "Created At", "Updated At"]
    ws.append(headers)
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    # Data
    for idx, branch in enumerate(branches_qs, start=1):
        ws.append([
            idx,
            branch.code,
            branch.name,
            branch.address or "",
            branch.phone or "",
            branch.email or "",
            "Active" if branch.is_active else "Inactive",
            branch.created_at.strftime("%d-%m-%Y %H:%M") if branch.created_at else "",
            branch.updated_at.strftime("%d-%m-%Y %H:%M") if branch.updated_at else "",
        ])

    # Borders & alignment for data rows
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    # Column widths
    column_widths = [6, 16, 28, 40, 18, 30, 12, 20, 20]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    import datetime
    filename = f"branches_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response