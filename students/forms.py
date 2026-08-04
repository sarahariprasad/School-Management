# students/forms.py
from django import forms
from staff.models import StaffProfile
from .models import Student


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        # include all fields, or explicitly list them
        fields = "__all__"
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "admission_date": forms.DateInput(attrs={"type": "date"}),
            "inactive_date": forms.DateInput(attrs={"type": "date"}),  # ✅ date picker
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ✅ Only show active teachers
        self.fields["assigned_teacher"].queryset = StaffProfile.objects.filter(is_active=True, designation="Teacher")
