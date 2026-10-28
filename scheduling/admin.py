from django.contrib import admin
from . import models


@admin.register(models.TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ("__str__", "is_active")


@admin.register(models.TherapistSlot)
class TherapistSlotAdmin(admin.ModelAdmin):
    list_display = ("staff", "time_slot")
    list_filter = ("staff",)


@admin.register(models.SlotAssignment)
class SlotAssignmentAdmin(admin.ModelAdmin):
    list_display = ("student", "therapy", "staff", "time_slot", "weekdays", "start_date", "end_date")
    list_filter = ("therapy", "staff")
    search_fields = ("student__name", "student__student_id")


@admin.register(models.TherapySession)
class TherapySessionAdmin(admin.ModelAdmin):
    list_display = ("date", "time_slot", "student", "therapy", "staff", "status")
    list_filter = ("status", "date", "therapy")
    search_fields = ("student__name", "student__student_id")


admin.site.register(models.StudentAttendance)
admin.site.register(models.StaffAttendance)
admin.site.register(models.GroupSession)
admin.site.register(models.GroupSessionAttendance)
