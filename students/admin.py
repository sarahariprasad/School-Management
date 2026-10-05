# students/admin.py
from django.contrib import admin

from .models import (
    Student,
    Group,
    GroupHistory,
    GroupStaffAssignment,
    Therapy,
    StudentTherapy,
    StatusHistory,
    Remark,
)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name", "description")


class GroupStaffAssignmentInline(admin.TabularInline):
    """Manage which staff are assigned to this group directly from the Group admin page."""
    model = GroupStaffAssignment
    extra = 0
    fields = ("staff", "is_active", "assigned_on", "ended_on")
    autocomplete_fields = ("staff",)


@admin.register(GroupStaffAssignment)
class GroupStaffAssignmentAdmin(admin.ModelAdmin):
    list_display = ("group", "staff", "is_active", "assigned_on", "ended_on")
    list_filter = ("group", "is_active")
    search_fields = ("staff__employee_id", "staff__user__first_name", "staff__user__last_name")
    autocomplete_fields = ("staff",)


@admin.register(Therapy)
class TherapyAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


class StudentTherapyInline(admin.TabularInline):
    """The M2M `therapies` field on Student has a `through` model, so it can't
    use filter_horizontal/filter_vertical — Django raises ImproperlyConfigured
    if you try. Manage enrollments via this inline instead."""
    model = StudentTherapy
    extra = 0
    fields = ("therapy", "staff", "frequency", "start_date", "end_date", "is_active")
    autocomplete_fields = ("staff",)


@admin.register(StudentTherapy)
class StudentTherapyAdmin(admin.ModelAdmin):
    list_display = ("student", "therapy", "staff", "frequency", "start_date", "end_date", "is_active")
    list_filter = ("therapy", "is_active")
    search_fields = ("student__student_id", "student__name", "therapy__name")
    autocomplete_fields = ("student", "staff")


class RemarkInline(admin.TabularInline):
    model = Remark
    extra = 0
    fields = ("category", "remark_text", "created_by", "created_at", "sent_to_parents", "sent_at")
    readonly_fields = ("created_at", "sent_to_parents", "sent_at")


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    fields = ("status", "changed_on", "reason", "changed_by")


class GroupHistoryInline(admin.TabularInline):
    model = GroupHistory
    extra = 0
    fields = ("group", "changed_on", "reason", "changed_by")


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "student_id",
        "name",
        "group",
        "admission_date",
        "is_active",
        "inactive_date",
    )
    list_filter = ("group", "gender", "is_active")
    search_fields = ("student_id", "name", "mother_name", "father_name")
    autocomplete_fields = ("group", "student_branch")
    readonly_fields = ("admission_date",)
    # therapies is a M2M with a `through` model — cannot use filter_horizontal here,
    # so enrollments (with their therapist, frequency, dates) are managed via the inline below.
    inlines = [StudentTherapyInline, StatusHistoryInline, GroupHistoryInline, RemarkInline]

    fieldsets = (
        ("Student Details", {
            "fields": ("student_id", "name", "date_of_birth", "gender", "photo", "address")
        }),
        ("Parent Details", {
            "fields": (
                "mother_name", "mother_phone", "mother_email", "mother_occupation", "mother_photo",
                "father_name", "father_phone", "father_email", "father_occupation", "father_photo",
            )
        }),
        ("Group", {
            "fields": ("group", "student_branch")
        }),
        ("Status", {
            "fields": ("is_active", "inactive_date")
        }),
        ("Documents", {
            "fields": ("medical_documents",)
        }),
        ("System Info", {
            "fields": ("admission_date",)
        }),
    )


@admin.register(StatusHistory)
class StatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("student", "status", "changed_on", "reason", "changed_by")
    list_filter = ("status",)
    search_fields = ("student__student_id", "student__name")


@admin.register(GroupHistory)
class GroupHistoryAdmin(admin.ModelAdmin):
    list_display = ("student", "group", "changed_on", "reason", "changed_by")
    list_filter = ("group",)
    search_fields = ("student__student_id", "student__name")


@admin.register(Remark)
class RemarkAdmin(admin.ModelAdmin):
    list_display = ("student", "category", "created_at", "created_by", "sent_to_parents")
    list_filter = ("category", "sent_to_parents")
    search_fields = ("student__student_id", "student__name", "remark_text")