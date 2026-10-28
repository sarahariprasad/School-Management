from django import forms

from staff.models import StaffProfile
from students.models import Student
from .models import (
    DEFAULT_WEEKDAYS, WEEKDAYS, GroupSession, SlotAssignment, TherapySession, TimeSlot,
)


class BootstrapMixin:
    def style(self):
        for f in self.fields.values():
            w = f.widget
            if isinstance(w, forms.HiddenInput):
                continue
            if isinstance(w, forms.CheckboxSelectMultiple):
                w.attrs["class"] = "btn-check"          # rendered as pill toggles
            elif isinstance(w, forms.CheckboxInput):
                w.attrs["class"] = "form-check-input"
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs["class"] = "form-select"
            else:
                w.attrs["class"] = "form-control"


def _staff_label(s):
    return f"{s.full_name} ({s.therapy or 'no therapy'})"


class SlotAssignmentForm(BootstrapMixin, forms.ModelForm):
    weekdays = forms.MultipleChoiceField(
        choices=WEEKDAYS, widget=forms.CheckboxSelectMultiple,
        initial=DEFAULT_WEEKDAYS.split(","), label="Days",
    )

    class Meta:
        model = SlotAssignment
        fields = ["student", "therapy", "staff", "time_slot", "weekdays",
                  "start_date", "end_date", "notes"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        labels = {"end_date": "End date (leave blank to continue until the student is inactive)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = Student.objects.filter(is_active=True).order_by("name")
        self.fields["staff"].queryset = StaffProfile.objects.filter(
            is_active=True, therapy__isnull=False).select_related("user", "therapy")
        self.fields["staff"].label_from_instance = _staff_label
        self.fields["time_slot"].queryset = TimeSlot.objects.filter(is_active=True)
        self.style()

    def clean_weekdays(self):
        return ",".join(sorted(self.cleaned_data["weekdays"]))


class TherapySessionForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = TherapySession
        fields = ["student", "therapy", "staff", "date", "time_slot",
                  "status", "absence_reason", "notes", "rescheduled_from"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "rescheduled_from": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = Student.objects.filter(is_active=True).order_by("name")
        self.fields["staff"].queryset = StaffProfile.objects.filter(is_active=True).select_related("user")
        self.fields["staff"].label_from_instance = _staff_label
        self.fields["time_slot"].queryset = TimeSlot.objects.filter(is_active=True)
        self.style()


class GroupSessionForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = GroupSession
        fields = ["group", "date", "start_time", "end_time", "staff",
                  "activity", "status", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = StaffProfile.objects.filter(is_active=True).select_related("user")
        self.fields["staff"].label_from_instance = lambda s: s.full_name
        self.style()
