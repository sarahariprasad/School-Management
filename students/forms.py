
import logging

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from staff.models import StaffProfile

from .models import (
    Student,
    Remark,
    Group,
    Therapy,
    StudentTherapy,
    GroupStaffAssignment,
)

logger = logging.getLogger(__name__)


class StudentForm(forms.ModelForm):
    """
    Create or edit a student with an optional group and zero or more
    therapy enrollments.
    """

    therapies = forms.ModelMultipleChoiceField(
        queryset=Therapy.objects.all().order_by("name"),
        required=False,
        label="Therapies",
        widget=forms.CheckboxSelectMultiple(),
    )

    class Meta:
        model = Student
        fields = [
            "student_id",
            "name",
            "date_of_birth",
            "gender",
            "group",
            "therapies",
            "student_branch",
            "is_active",
            "inactive_date",
            "mother_name",
            "father_name",
            "mother_phone",
            "father_phone",
            "mother_email",
            "father_email",
            "mother_occupation",
            "father_occupation",
            "mother_photo",
            "father_photo",
            "photo",
            "medical_documents",
            "address",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
            "inactive_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "form-control",
                }
            ),
            "student_branch": forms.Select(
                attrs={"class": "form-select"}
            ),
            "group": forms.Select(
                attrs={"class": "form-select"}
            ),
            "gender": forms.Select(
                attrs={"class": "form-select"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Keep student ID immutable during editing.
        if self.instance and self.instance.pk:
            self.fields["student_id"].disabled = True

        # Both group and therapies are optional.
        self.fields["group"].required = False
        self.fields["group"].empty_label = "Not yet assigned"
        self.fields["therapies"].required = False

        # Preselect existing active therapies when editing.
        if self.instance and self.instance.pk:
            self.fields["therapies"].initial = Therapy.objects.filter(
                enrollments__student=self.instance,
                enrollments__is_active=True,
            ).distinct()

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")

        if dob and dob > timezone.now().date():
            raise ValidationError(
                "Date of birth cannot be in the future."
            )

        return dob

    def clean(self):
        cleaned_data = super().clean()

        mother_phone = cleaned_data.get("mother_phone")
        father_phone = cleaned_data.get("father_phone")
        mother_email = cleaned_data.get("mother_email")
        father_email = cleaned_data.get("father_email")

        # Require at least one parent contact method.
        if not any(
            [
                mother_phone,
                father_phone,
                mother_email,
                father_email,
            ]
        ):
            raise ValidationError(
                "Please provide at least one parent phone number "
                "or email address."
            )

        is_active = cleaned_data.get("is_active")
        inactive_date = cleaned_data.get("inactive_date")

        if is_active and inactive_date:
            cleaned_data["inactive_date"] = None

        return cleaned_data

    def save_therapies(self, student):
        """
        Synchronize selected therapies with the student's enrollments.

        Existing active enrollments retain their therapist, frequency,
        and start date. Deselected enrollments are ended, not deleted.
        """

        selected_therapies = self.cleaned_data.get("therapies")
        today = timezone.now().date()

        # End active enrollments whose therapies were deselected.
        student.therapy_enrollments.filter(
            is_active=True
        ).exclude(
            therapy__in=selected_therapies
        ).update(
            is_active=False,
            end_date=today,
        )

        # Create enrollments for newly selected therapies.
        for therapy in selected_therapies:
            active_enrollment_exists = (
                student.therapy_enrollments.filter(
                    therapy=therapy,
                    is_active=True,
                ).exists()
            )

            if not active_enrollment_exists:
                StudentTherapy.objects.create(
                    student=student,
                    therapy=therapy,
                    start_date=today,
                    is_active=True,
                )


class RemarkForm(forms.ModelForm):
    send_email = forms.BooleanField(
        required=False,
        initial=False,
        label="Email this remark to parents now",
    )

    class Meta:
        model = Remark
        fields = ["category", "remark_text"]
        widgets = {
            "category": forms.Select(
                attrs={"class": "form-select"}
            ),
            "remark_text": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "form-control",
                    "placeholder": "Progress note / remark...",
                }
            ),
        }

    def clean_remark_text(self):
        text = self.cleaned_data.get("remark_text", "").strip()

        if not text:
            raise ValidationError(
                "Remark text cannot be empty."
            )

        return text


class StatusChangeForm(forms.Form):
    is_active = forms.TypedChoiceField(
        choices=[
            (True, "Active"),
            (False, "Inactive"),
        ],
        coerce=lambda x: x == "True",
        widget=forms.RadioSelect,
        label="Status",
    )

    reason = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Reason (optional)",
            }
        ),
    )


class GroupChangeForm(forms.Form):
    """Move a student to another group with a logged reason."""

    group = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        label="New Group",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    reason = forms.CharField(
        required=False,
        max_length=255,
        initial="Reassessment",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": (
                    "e.g. Reassessment, Progress review"
                ),
            }
        ),
    )


class BulkGroupReassignForm(forms.Form):
    """Move active students from one group to another."""

    from_group = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        label="Move students currently in",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    to_group = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        label="Move them to",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
    )

    reason = forms.CharField(
        required=False,
        max_length=255,
        initial="Bulk group reassignment",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "e.g. Term 2 review",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        from_group = cleaned_data.get("from_group")
        to_group = cleaned_data.get("to_group")

        if (
            from_group
            and to_group
            and from_group == to_group
        ):
            raise ValidationError(
                "'Move students currently in' and "
                "'Move them to' must be different groups."
            )

        return cleaned_data


class StudentTherapyForm(forms.ModelForm):
    """
    Add or edit one therapy enrollment, including therapist,
    frequency, dates, and active status.
    """

    class Meta:
        model = StudentTherapy
        fields = [
            "therapy",
            "staff",
            "frequency",
            "start_date",
            "end_date",
            "is_active",
        ]
        widgets = {
            "therapy": forms.Select(
                attrs={"class": "form-select"}
            ),
            "staff": forms.Select(
                attrs={"class": "form-select"}
            ),
            "frequency": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. 3x/week",
                }
            ),
            "start_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
            "end_date": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control",
                }
            ),
            "is_active": forms.Select(
                choices=[
                    (True, "Active"),
                    (False, "Ended"),
                ],
                attrs={"class": "form-select"},
            ),
        }

    def __init__(self, *args, student=None, **kwargs):
        self.student = student
        super().__init__(*args, **kwargs)

        self.fields["staff"].queryset = (
            StaffProfile.objects.filter(is_active=True)
            .order_by("employee_id")
        )
        self.fields["staff"].required = False
        self.fields["staff"].empty_label = "Unassigned"
        self.fields["end_date"].required = False

        # New enrollments always start active.
        if not (self.instance and self.instance.pk):
            del self.fields["is_active"]

    def clean(self):
        cleaned_data = super().clean()

        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        therapy = cleaned_data.get("therapy")
        is_active = cleaned_data.get("is_active", True)

        if start_date and end_date and end_date < start_date:
            raise ValidationError(
                "End date cannot be before the start date."
            )

        if self.student and therapy and is_active:
            clashing = StudentTherapy.objects.filter(
                student=self.student,
                therapy=therapy,
                is_active=True,
            )

            if self.instance.pk:
                clashing = clashing.exclude(
                    pk=self.instance.pk
                )

            if clashing.exists():
                raise ValidationError(
                    f"{self.student.name} already has an active "
                    f"{therapy} enrollment. Deactivate it first, "
                    "or edit that enrollment instead."
                )

        return cleaned_data


class GroupStaffAssignmentForm(forms.ModelForm):
    """Assign an active staff member to a group."""

    class Meta:
        model = GroupStaffAssignment
        fields = ["staff", "is_active"]
        widgets = {
            "staff": forms.Select(
                attrs={"class": "form-select"}
            ),
        }

    def __init__(self, *args, group=None, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)

        self.fields["staff"].queryset = (
            StaffProfile.objects.filter(is_active=True)
            .order_by("employee_id")
        )

    def clean(self):
        cleaned_data = super().clean()

        staff = cleaned_data.get("staff")

        if (
            self.group
            and staff
            and cleaned_data.get("is_active")
        ):
            clashing = GroupStaffAssignment.objects.filter(
                group=self.group,
                staff=staff,
                is_active=True,
            )

            if self.instance.pk:
                clashing = clashing.exclude(
                    pk=self.instance.pk
                )

            if clashing.exists():
                raise ValidationError(
                    f"{staff.full_name} is already actively "
                    f"assigned to {self.group}."
                )

        return cleaned_data


class StudentSearchForm(forms.Form):
    """Validate search and filtering query parameters."""

    q = forms.CharField(required=False)

    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All"),
            ("active", "Active"),
            ("inactive", "Inactive"),
        ],
    )

    group = forms.IntegerField(required=False)
    therapy = forms.IntegerField(required=False)
    staff = forms.IntegerField(required=False)
    admitted_from = forms.DateField(required=False)
    admitted_to = forms.DateField(required=False)
