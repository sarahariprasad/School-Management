# students/forms.py
import logging

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from staff.models import StaffProfile
from .models import Student, Remark, Group, Therapy, StudentTherapy, GroupStaffAssignment

logger = logging.getLogger(__name__)


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        # Explicit field list so TrackableMixin fields (created_by, updated_by,
        # created_at, updated_at) do NOT appear as unwanted dropdowns in the form.
        # NOTE: 'therapies' is intentionally excluded — it's a M2M through
        # StudentTherapy with extra required fields (staff, frequency, dates),
        # which ModelForm/save_m2m() cannot handle. Therapy enrollments are
        # managed separately via StudentTherapyForm.
        fields = [
            "student_id", "name", "date_of_birth", "gender",
            "group", "student_branch",
            "is_active", "inactive_date",
            "mother_name", "father_name", "mother_phone", "father_phone",
            "mother_email", "father_email", "mother_occupation", "father_occupation",
            "mother_photo", "father_photo", "photo",
            "medical_documents",
            "address",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "inactive_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "address": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "student_branch": forms.Select(attrs={"class": "form-select"}),
            "group": forms.Select(attrs={"class": "form-select"}),
            "gender": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # make student_id read-only on edit (immutable identifier)
        if self.instance and self.instance.pk:
            self.fields["student_id"].disabled = True
        self.fields["group"].required = False
        self.fields["group"].empty_label = "Not yet assigned"

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if dob and dob > timezone.now().date():
            raise ValidationError("Date of birth cannot be in the future.")
        return dob

    def clean(self):
        cleaned_data = super().clean()
        mother_phone = cleaned_data.get("mother_phone")
        father_phone = cleaned_data.get("father_phone")
        mother_email = cleaned_data.get("mother_email")
        father_email = cleaned_data.get("father_email")

        # require at least one way to reach a parent, since progress remarks
        # and status updates depend on this
        if not any([mother_phone, father_phone, mother_email, father_email]):
            raise ValidationError(
                "Please provide at least one parent phone number or email address."
            )

        is_active = cleaned_data.get("is_active")
        inactive_date = cleaned_data.get("inactive_date")
        if is_active and inactive_date:
            # not fatal, but Student.save() will clear it anyway — warn via non-field error
            # only if the user explicitly set both, to avoid silent surprises
            cleaned_data["inactive_date"] = None

        return cleaned_data


class RemarkForm(forms.ModelForm):
    send_email = forms.BooleanField(
        required=False, initial=False, label="Email this remark to parents now"
    )

    class Meta:
        model = Remark
        fields = ["category", "remark_text"]
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "remark_text": forms.Textarea(
                attrs={"rows": 4, "class": "form-control", "placeholder": "Progress note / remark..."}
            ),
        }

    def clean_remark_text(self):
        text = self.cleaned_data.get("remark_text", "").strip()
        if not text:
            raise ValidationError("Remark text cannot be empty.")
        return text


class StatusChangeForm(forms.Form):
    is_active = forms.TypedChoiceField(
        choices=[(True, "Active"), (False, "Inactive")],
        coerce=lambda x: x == "True",
        widget=forms.RadioSelect,
        label="Status",
    )
    reason = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Reason (optional)"}),
    )


class GroupChangeForm(forms.Form):
    """Used on the student detail page to move a single student to a new
    group (e.g. reassessment moving them from Orange to Green), with a
    logged reason. Replaces the old ClassChangeForm."""
    group = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        label="New Group",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    reason = forms.CharField(
        required=False,
        max_length=255,
        initial="Reassessment",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g. Reassessment, Progress review"}
        ),
    )


class BulkGroupReassignForm(forms.Form):
    """Moves every active student currently in one group into another group
    in one go - e.g. moving all of 'Orange' into 'Green' after a review cycle.
    Replaces the old BulkPromoteForm (there's no grade-promotion concept here)."""
    from_group = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        label="Move students currently in",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    to_group = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        label="Move them to",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    reason = forms.CharField(
        required=False,
        max_length=255,
        initial="Bulk group reassignment",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Term 2 review"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        from_group = cleaned_data.get("from_group")
        to_group = cleaned_data.get("to_group")
        if from_group and to_group and from_group == to_group:
            raise ValidationError("'Move students currently in' and 'Move them to' must be different groups.")
        return cleaned_data


class StudentTherapyForm(forms.ModelForm):
    """Add or edit a single therapy enrollment for a student — each
    enrollment carries its own therapist, frequency, and active status."""

    class Meta:
        model = StudentTherapy
        fields = ["therapy", "staff", "frequency", "start_date", "end_date", "is_active"]
        widgets = {
            "therapy": forms.Select(attrs={"class": "form-select"}),
            "staff": forms.Select(attrs={"class": "form-select"}),
            "frequency": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. 3x/week"}
            ),
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "is_active": forms.Select(
                choices=[(True, "Active"), (False, "Ended")],
                attrs={"class": "form-select"},
            ),
        }

    def __init__(self, *args, student=None, **kwargs):
        self.student = student
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = StaffProfile.objects.filter(is_active=True).order_by("employee_id")
        self.fields["staff"].required = False
        self.fields["staff"].empty_label = "Unassigned"
        self.fields["end_date"].required = False

        # A brand-new enrollment always starts Active - there's nothing
        # meaningful to choose yet, so don't show the status field on the
        # add form at all. construct_instance() then leaves is_active at
        # the model's own default (True) since it's absent from cleaned_data.
        # Editing an existing enrollment keeps the field so status can be
        # changed explicitly (e.g. marking it Ended with an end date).
        if not (self.instance and self.instance.pk):
            del self.fields["is_active"]

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        therapy = cleaned_data.get("therapy")
        is_active = cleaned_data.get("is_active", True)  # add form has no field -> always True

        if start_date and end_date and end_date < start_date:
            raise ValidationError("End date cannot be before the start date.")

        # enforce "one active enrollment per therapy per student" at the form
        # level too, so the user gets a clean message instead of an IntegrityError
        if self.student and therapy and is_active:
            clashing = StudentTherapy.objects.filter(
                student=self.student, therapy=therapy, is_active=True
            )
            if self.instance.pk:
                clashing = clashing.exclude(pk=self.instance.pk)
            if clashing.exists():
                raise ValidationError(
                    f"{self.student.name} already has an active {therapy} enrollment. "
                    "Deactivate it first, or edit that enrollment instead."
                )
        return cleaned_data

class GroupStaffAssignmentForm(forms.ModelForm):
    """Assign a staff member to a group (multiple staff per group allowed)."""

    class Meta:
        model = GroupStaffAssignment
        fields = ["staff", "is_active"]
        widgets = {
            "staff": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, group=None, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = StaffProfile.objects.filter(is_active=True).order_by("employee_id")

    def clean(self):
        cleaned_data = super().clean()
        staff = cleaned_data.get("staff")
        if self.group and staff and cleaned_data.get("is_active"):
            clashing = GroupStaffAssignment.objects.filter(
                group=self.group, staff=staff, is_active=True
            )
            if self.instance.pk:
                clashing = clashing.exclude(pk=self.instance.pk)
            if clashing.exists():
                raise ValidationError(f"{staff.full_name} is already actively assigned to {self.group}.")
        return cleaned_data


class StudentSearchForm(forms.Form):
    """Not bound to a model - purely for validating/cleaning the search/filter
    querystring on the list view."""
    q = forms.CharField(required=False)
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All"), ("active", "Active"), ("inactive", "Inactive")],
    )
    group = forms.IntegerField(required=False)
    therapy = forms.IntegerField(required=False)
    staff = forms.IntegerField(required=False)
    admitted_from = forms.DateField(required=False)
    admitted_to = forms.DateField(required=False)