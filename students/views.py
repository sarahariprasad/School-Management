# students/views.py
import logging

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldError, PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from staff.models import StaffProfile

from .forms import (
    BulkGroupReassignForm,
    GroupChangeForm,
    GroupStaffAssignmentForm,
    RemarkForm,
    StatusChangeForm,
    StudentForm,
    StudentTherapyForm,
)
from .models import Group, GroupStaffAssignment, Student, StudentTherapy, Therapy
from core.permissions import role_required
from .utils import (
    export_remarks_to_excel,
    export_single_student_to_excel,
    export_students_to_excel,
    send_remark_email,
)

from audit_log.services import build_field_changes, log_audit, snapshot_instance
from audit_log.models import AuditLog

logger = logging.getLogger(__name__)


def _get_staff_profile(user):
    """Safely fetch the StaffProfile linked to the current user."""
    return getattr(user, "staff_profile", None)


def _filter_students(request):
    """Shared search/filter logic used by both the list view and the Excel export,
    so the exported file always matches whatever the user is currently looking at."""
    query = request.GET.get("q")
    group_id = request.GET.get("group")
    staff_id = request.GET.get("staff")
    therapy_id = request.GET.get("therapy")
    status = request.GET.get("status")
    admitted_from = request.GET.get("admitted_from")
    admitted_to = request.GET.get("admitted_to")

    students = Student.objects.select_related("group", "updated_by").prefetch_related(
        "therapy_enrollments__therapy", "therapy_enrollments__staff"
    )
    error_message = None

    try:
        if query:
            students = students.filter(
                Q(name__icontains=query)
                | Q(student_id__icontains=query)
                | Q(group__name__icontains=query)
            )
    except FieldError:
        logger.warning("Invalid search field used in student search: %r", query)
        students = students.none()
        error_message = "Invalid search field. Please search by name, ID, or group."

    if group_id:
        students = students.filter(group_id=group_id)
    if staff_id:
        # staff touching this student either via their group or a therapy enrollment
        students = students.filter(
            Q(group__staff_assignments__staff_id=staff_id, group__staff_assignments__is_active=True)
            | Q(therapy_enrollments__staff_id=staff_id)
        )
    if therapy_id:
        students = students.filter(therapy_enrollments__therapy_id=therapy_id)
    if status == "active":
        students = students.filter(is_active=True)
    elif status == "inactive":
        students = students.filter(is_active=False)
    if admitted_from:
        students = students.filter(admission_date__gte=admitted_from)
    if admitted_to:
        students = students.filter(admission_date__lte=admitted_to)

    return students.distinct(), error_message


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN", "STAFF")
def student_list(request):
    try:
        students, error_message = _filter_students(request)
    except Exception:
        logger.exception("Failed to load student list with filters=%s", request.GET.dict())
        messages.error(request, "Something went wrong while loading students. Please try again.")
        students, error_message = Student.objects.none(), None

    context = {
        "students": students,
        "error_message": error_message,
        "groups": Group.objects.all(),
        "staff_members": StaffProfile.objects.filter(is_active=True).order_by("employee_id"),
        "therapies": Therapy.objects.all(),
        "filters": request.GET,
    }
    return render(request, "students/student_list.html", context)


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def student_export_excel(request):
    try:
        students, _ = _filter_students(request)
        return export_students_to_excel(students)
    except Exception:
        logger.exception("Student Excel export failed")
        messages.error(request, "Could not generate the export file. Please try again.")
        return redirect("student_list")


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def student_detail(request, pk):
    student = get_object_or_404(
        Student.objects.select_related("group").prefetch_related(
            "therapy_enrollments__therapy",
            "therapy_enrollments__staff",
            "remarks",
            "status_history",
            "group_history__group",
        ),
        pk=pk,
    )

    student_ct = ContentType.objects.get_for_model(Student)
    audit_logs = (
        AuditLog.objects.filter(content_type=student_ct, object_id=student.pk)
        .select_related("user")
        .order_by("-action_time")[:20]
    )

    group_staff = (
        StaffProfile.objects.filter(
            group_assignments__group=student.group, group_assignments__is_active=True
        ).distinct()
        if student.group_id
        else StaffProfile.objects.none()
    )

    context = {
        "student": student,
        "remarks": student.remarks.all(),
        "status_history": student.status_history.all(),
        "group_history": student.group_history.all(),
        "therapy_enrollments": student.therapy_enrollments.select_related("therapy", "staff"),
        "group_staff": group_staff,
        "audit_logs": audit_logs,
        "remark_form": RemarkForm(),
        "status_form": StatusChangeForm(initial={"is_active": student.is_active}),
        "group_form": GroupChangeForm(initial={"group": student.group_id}),
        "therapy_form": StudentTherapyForm(student=student),
    }
    return render(request, "students/student_detail.html", context)


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def student_create(request):
    if request.method == "POST":
        form = StudentForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    student = form.save(commit=False)
                    # student_form.html has no Status tab, so the is_active checkbox is
                    # never submitted - Django then treats it as an unchecked box (False),
                    # even though the model default is True. Force it explicitly here so
                    # every newly created student starts Active.
                    student.is_active = True
                    student.inactive_date = None
                    student.created_by = request.user
                    student.updated_by = request.user
                    student.save()

                    log_audit(request.user, student, "CREATE", snapshot=snapshot_instance(student))

                messages.success(request, f"Student {student.name} was added successfully.")
                return redirect("student_detail", pk=student.pk)
            except IntegrityError:
                logger.exception("IntegrityError creating student with data=%s", form.cleaned_data)
                messages.error(
                    request,
                    "Could not save this student — a student with that ID may already exist.",
                )
            except Exception:
                logger.exception("Unexpected error creating student")
                messages.error(request, "An unexpected error occurred while saving. Please try again.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = StudentForm()
    return render(request, "students/student_form.html", {"form": form})


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)

    student_ct = ContentType.objects.get_for_model(Student)
    audit_logs = (
        AuditLog.objects.filter(content_type=student_ct, object_id=student.pk)
        .select_related("user")
        .order_by("-action_time")[:20]
    )

    if request.method == "POST":
        old_student = Student.objects.get(pk=student.pk)
        form = StudentForm(request.POST, request.FILES, instance=student)
        if form.is_valid():
            try:
                with transaction.atomic():
                    student = form.save(commit=False)
                    student.updated_by = request.user
                    student.save()

                    changes = build_field_changes(old_student, student)
                    if changes:
                        log_audit(request.user, student, "UPDATE", field_changes=changes)

                messages.success(request, f"Student {student.name} was updated successfully.")
                return redirect("student_detail", pk=student.pk)
            except IntegrityError:
                logger.exception("IntegrityError updating student pk=%s", pk)
                messages.error(request, "Could not save changes due to a data conflict. Please try again.")
            except Exception:
                logger.exception("Unexpected error updating student pk=%s", pk)
                messages.error(request, "An unexpected error occurred while saving. Please try again.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = StudentForm(instance=student)

    return render(
        request,
        "students/student_edit.html",
        {"form": form, "student": student, "audit_logs": audit_logs},
    )


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def add_remark(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == "POST":
        form = RemarkForm(request.POST)
        if form.is_valid():
            try:
                remark = form.save(commit=False)
                remark.student = student
                remark.created_by = _get_staff_profile(request.user)
                remark.save()

                if form.cleaned_data.get("send_email"):
                    if send_remark_email(remark):
                        messages.success(request, "Remark saved and emailed to parents.")
                    else:
                        messages.warning(
                            request,
                            "Remark saved, but no parent email was found on file (or sending failed).",
                        )
                else:
                    messages.success(request, "Remark saved.")
            except Exception:
                logger.exception("Failed to save remark for student pk=%s", pk)
                messages.error(request, "Could not save this remark. Please try again.")
        else:
            messages.error(request, "Please correct the errors below.")
    return redirect("student_detail", pk=pk)


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def toggle_status(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == "POST":
        form = StatusChangeForm(request.POST)
        if form.is_valid():
            new_status = form.cleaned_data["is_active"]
            reason = form.cleaned_data.get("reason")

            if new_status == student.is_active:
                messages.info(request, f"Student is already {'active' if new_status else 'inactive'}.")
            else:
                try:
                    with transaction.atomic():
                        old_status = student.is_active
                        student.is_active = new_status
                        student.save()  # StatusHistory entry is created automatically in Student.save()

                        latest_history = student.status_history.first()
                        staff = _get_staff_profile(request.user)
                        if latest_history:
                            latest_history.reason = reason
                            latest_history.changed_by = staff
                            latest_history.save(update_fields=["reason", "changed_by"])

                        log_audit(
                            request.user,
                            student,
                            "UPDATE",
                            field_changes={
                                "is_active": {
                                    "old": "Active" if old_status else "Inactive",
                                    "new": "Active" if new_status else "Inactive",
                                }
                            },
                        )
                    messages.success(request, "Student status updated.")
                except Exception:
                    logger.exception("Failed to toggle status for student pk=%s", pk)
                    messages.error(request, "Could not update status. Please try again.")
        else:
            messages.error(request, "Please correct the errors below.")
    return redirect("student_detail", pk=pk)


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def change_group(request, pk):
    """Move a single student to a different group (Red/Green/Orange), e.g.
    after a progress reassessment. Replaces the old change_class view."""
    student = get_object_or_404(Student, pk=pk)
    if request.method == "POST":
        form = GroupChangeForm(request.POST)
        if form.is_valid():
            new_group = form.cleaned_data["group"]
            reason = form.cleaned_data.get("reason") or "Reassessment"

            if new_group.id == student.group_id:
                messages.info(request, f"{student.name} is already in {new_group}.")
            else:
                try:
                    with transaction.atomic():
                        old_group = student.group
                        student.group = new_group
                        student.save()  # GroupHistory entry is created automatically in Student.save()

                        latest_history = student.group_history.first()
                        staff = _get_staff_profile(request.user)
                        if latest_history:
                            latest_history.reason = reason
                            latest_history.changed_by = staff
                            latest_history.save(update_fields=["reason", "changed_by"])

                        changes = {}
                        if old_group:
                            changes["group"] = {"old": str(old_group), "new": str(new_group)}
                        log_audit(request.user, student, "UPDATE", field_changes=changes)

                    messages.success(request, f"{student.name} moved to {new_group}.")
                except Exception:
                    logger.exception("Failed to change group for student pk=%s", pk)
                    messages.error(request, "Could not update the group. Please try again.")
        else:
            messages.error(request, "Please correct the errors below.")
    return redirect("student_detail", pk=pk)


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def bulk_group_reassign(request):
    """Move every active student in one group into another group in a single
    action - e.g. after a term-end review cycle. Replaces bulk_promote."""
    if request.method == "POST":
        form = BulkGroupReassignForm(request.POST)
        if form.is_valid():
            from_group = form.cleaned_data["from_group"]
            to_group = form.cleaned_data["to_group"]
            reason = form.cleaned_data.get("reason") or f"Moved from {from_group} to {to_group}"

            try:
                with transaction.atomic():
                    students = Student.objects.filter(group=from_group, is_active=True)
                    staff = _get_staff_profile(request.user)
                    reassigned_count = 0
                    for student in students:
                        student.group = to_group
                        student.save()  # logs a GroupHistory row for each student
                        latest_history = student.group_history.first()
                        if latest_history:
                            latest_history.reason = reason
                            latest_history.changed_by = staff
                            latest_history.save(update_fields=["reason", "changed_by"])
                        reassigned_count += 1

                if reassigned_count:
                    messages.success(
                        request, f"Moved {reassigned_count} student(s) from {from_group} to {to_group}."
                    )
                else:
                    messages.info(request, f"No active students found in {from_group}.")
                return redirect("student_list")
            except Exception:
                logger.exception(
                    "Bulk group reassignment failed (from=%s to=%s)", from_group, to_group
                )
                messages.error(request, "Could not complete the bulk reassignment. No changes were saved.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = BulkGroupReassignForm()
    return render(request, "students/bulk_group_reassign.html", {"form": form})


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def add_therapy_enrollment(request, pk):
    """Enroll a student in a therapy, assigning a specific therapist."""
    student = get_object_or_404(Student, pk=pk)
    if request.method == "POST":
        form = StudentTherapyForm(request.POST, student=student)
        if form.is_valid():
            try:
                with transaction.atomic():
                    enrollment = form.save(commit=False)
                    enrollment.student = student
                    enrollment.is_active = True  # new enrollments always start Active
                    enrollment.save()
                    log_audit(
                        request.user,
                        student,
                        "UPDATE",
                        field_changes={
                            "therapy_enrollment": {
                                "old": "",
                                "new": f"{enrollment.therapy} ({enrollment.staff or 'unassigned'})",
                            }
                        },
                    )
                messages.success(request, f"{enrollment.therapy} enrollment added for {student.name}.")
            except IntegrityError:
                logger.exception("IntegrityError adding therapy enrollment for student pk=%s", pk)
                messages.error(request, "Could not save this enrollment due to a data conflict.")
            except Exception:
                logger.exception("Unexpected error adding therapy enrollment for student pk=%s", pk)
                messages.error(request, "Could not save this enrollment. Please try again.")
        else:
            # surface form errors (incl. our "already has an active enrollment" check)
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect("student_detail", pk=pk)


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def edit_therapy_enrollment(request, pk, enrollment_pk):
    student = get_object_or_404(Student, pk=pk)
    enrollment = get_object_or_404(StudentTherapy, pk=enrollment_pk, student=student)
    if request.method == "POST":
        form = StudentTherapyForm(request.POST, instance=enrollment, student=student)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, f"{enrollment.therapy} enrollment updated for {student.name}.")
            except Exception:
                logger.exception("Failed to update therapy enrollment pk=%s", enrollment_pk)
                messages.error(request, "Could not update this enrollment. Please try again.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect("student_detail", pk=pk)


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def remove_therapy_enrollment(request, pk, enrollment_pk):
    """Deactivates rather than deletes, to preserve history."""
    student = get_object_or_404(Student, pk=pk)
    enrollment = get_object_or_404(StudentTherapy, pk=enrollment_pk, student=student)
    if request.method == "POST":
        try:
            enrollment.is_active = False
            enrollment.end_date = enrollment.end_date or timezone.now().date()
            enrollment.save(update_fields=["is_active", "end_date"])
            messages.success(request, f"{enrollment.therapy} enrollment ended for {student.name}.")
        except Exception:
            logger.exception("Failed to deactivate therapy enrollment pk=%s", enrollment_pk)
            messages.error(request, "Could not end this enrollment. Please try again.")
    return redirect("student_detail", pk=pk)


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def group_list(request):
    """Red / Green / Orange overview - each group's student count and assigned staff."""
    groups = Group.objects.prefetch_related("staff_assignments__staff", "students")
    return render(request, "students/group_list.html", {"groups": groups})


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def group_detail(request, pk):
    """A single group's students, its assigned staff, and a form to assign more staff."""
    group = get_object_or_404(
        Group.objects.prefetch_related("staff_assignments__staff", "students"), pk=pk
    )
    context = {
        "group": group,
        "students": group.students.all(),
        "staff_assignments": group.staff_assignments.filter(is_active=True).select_related("staff"),
        "assignment_form": GroupStaffAssignmentForm(group=group),
    }
    return render(request, "students/group_detail.html", context)


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def assign_group_staff(request, group_pk):
    """Assign a staff member to a group. A group can have multiple staff."""
    group = get_object_or_404(Group, pk=group_pk)
    if request.method == "POST":
        form = GroupStaffAssignmentForm(request.POST, group=group)
        if form.is_valid():
            try:
                assignment = form.save(commit=False)
                assignment.group = group
                assignment.save()
                messages.success(request, f"{assignment.staff.full_name} assigned to {group}.")
            except IntegrityError:
                logger.exception("IntegrityError assigning staff to group pk=%s", group_pk)
                messages.error(request, "Could not save this assignment due to a data conflict.")
            except Exception:
                logger.exception("Unexpected error assigning staff to group pk=%s", group_pk)
                messages.error(request, "Could not save this assignment. Please try again.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect("group_detail", pk=group_pk)


def export_remarks(request, pk):
    student = get_object_or_404(Student, pk=pk)
    try:
        return export_remarks_to_excel(student)
    except Exception:
        logger.exception("Remarks export failed for student pk=%s", pk)
        messages.error(request, "Could not generate the remarks export.")
        return redirect("student_detail", pk=pk)


def student_export_single_excel(request, pk):
    student = get_object_or_404(
        Student.objects.select_related("group").prefetch_related(
            "therapy_enrollments__therapy", "therapy_enrollments__staff", "remarks", "status_history"
        ),
        pk=pk,
    )
    try:
        return export_single_student_to_excel(student)
    except Exception:
        logger.exception("Single-student export failed for student pk=%s", pk)
        messages.error(request, "Could not generate the export file.")
        return redirect("student_detail", pk=pk)
