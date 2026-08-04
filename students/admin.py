from django.contrib import admin
from .models import Student, Class, Therapy

@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    list_display = ("name", "section")
    search_fields = ("name", "section")

@admin.register(Therapy)
class TherapyAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "student_id",
        "name",
        "student_class",
        "assigned_teacher",
        "admission_date",
    )
    list_filter = ("student_class", "assigned_teacher", "gender")
    search_fields = ("student_id", "name", "mother_name", "father_name")
    filter_horizontal = ("therapies",)  # nice UI for ManyToMany
    readonly_fields = ("admission_date",)

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
        ("Academic Details", {
            "fields": ("student_class", "assigned_teacher", "therapies")
        }),
        ("Documents", {
            "fields": ("medical_documents",)
        }),
        ("System Info", {
            "fields": ("admission_date",)
        }),
    )
