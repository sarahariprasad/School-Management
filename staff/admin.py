from django.contrib import admin
from .models import EducationRecord, StaffDocument, StaffProfile

@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "user", "department", "designation", "joining_date", "leaving_date", "is_active")
    list_filter = ("department", "is_active")
    search_fields = ("employee_id", "user__email", "user__first_name", "user__last_name")


admin.site.register(EducationRecord)
admin.site.register(StaffDocument)
