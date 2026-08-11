from django import forms
from django.forms import inlineformset_factory
from accounts.models import User
from branches.models import Branch
from .models import (
    EducationRecord, ExperienceHistory, PromotionHistory,
    SalaryIncrement, StaffDocument, StaffProfile,
)


# ── Widget helpers ──
def _text(attrs=None, placeholder=""):
    d = {"class": "form-control", "placeholder": placeholder}
    if attrs:
        d.update(attrs)
    return forms.TextInput(attrs=d)


def _email(placeholder="you@example.com"):
    return forms.EmailInput(attrs={"class": "form-control", "placeholder": placeholder, "type": "email"})


def _password(placeholder="Enter password"):
    return forms.PasswordInput(attrs={"class": "form-control", "placeholder": placeholder})


def _date():
    return forms.DateInput(attrs={"class": "form-control", "type": "date"})


def _textarea(rows=3, placeholder=""):
    return forms.Textarea(attrs={"class": "form-control", "rows": rows, "placeholder": placeholder})


def _select():
    return forms.Select(attrs={"class": "form-select"})


def _number(placeholder=""):
    return forms.NumberInput(attrs={"class": "form-control", "placeholder": placeholder})


def _file():
    return forms.FileInput(attrs={"class": "form-control", "type": "file"})


def _checkbox():
    return forms.CheckboxInput(attrs={"class": "form-check-input"})


# ═══════════════════════════════════════════════════════════════
# CREATE FORM (with User creation)
# ═══════════════════════════════════════════════════════════════
class StaffCreateForm(forms.ModelForm):
    # User fields
    email = forms.EmailField(
        widget=_email(),
        help_text="This becomes the staff member's login username.",
    )
    password = forms.CharField(
        widget=_password(),
        min_length=8,
        help_text="Minimum 8 characters.",
    )
    first_name = forms.CharField(max_length=150, widget=_text(placeholder="First name"))
    last_name = forms.CharField(max_length=150, required=False, widget=_text(placeholder="Last name"))
    role = forms.ChoiceField(
        choices=User.Role.choices,
        initial=User.Role.STAFF,
        widget=_select(),
    )
    primary_branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=True,
        widget=_select(),
        help_text="Home branch for the staff record.",
    )
    accessible_branches = forms.ModelMultipleChoiceField(
        queryset=Branch.objects.filter(is_active=True),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "4"}),
        help_text="Only needed for Finance Admin.",
    )

    class Meta:
        model = StaffProfile
        fields = [
            "employee_id", "gender", "date_of_birth", "department",
            "designation", "joining_date", "phone", "emergency_contact",
            "emergency_contact_name", "address", "city", "state",
            "postal_code", "address_proof_type", "address_proof",
            "photo", "is_active",
        ]
        widgets = {
            "employee_id": _text(placeholder="EMP001"),
            "gender": _select(),
            "date_of_birth": _date(),
            "department": _select(),
            "designation": _text(placeholder="e.g. Class Teacher"),
            "joining_date": _date(),
            "phone": _text(placeholder="+91 98765 43210"),
            "emergency_contact": _text(placeholder="+91 98765 43210"),
            "emergency_contact_name": _text(placeholder="Emergency contact name"),
            "address": _textarea(placeholder="Full address"),
            "city": _text(placeholder="City"),
            "state": _text(placeholder="State"),
            "postal_code": _text(placeholder="560001"),
            "address_proof_type": _text(placeholder="Aadhaar / PAN / Passport"),
            "address_proof": _file(),
            "photo": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "is_active": _checkbox(),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        if actor and not actor.is_system_admin:
            allowed_ids = list(actor.accessible_branches.values_list("id", flat=True))
            if actor.branch_id:
                allowed_ids.append(actor.branch_id)
            allowed = Branch.objects.filter(pk__in=allowed_ids)
            self.fields["role"].choices = [(User.Role.STAFF, "Staff")]
            self.fields["primary_branch"].queryset = allowed
            self.fields["accessible_branches"].queryset = allowed

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        primary = cleaned.get("primary_branch")
        accessible = cleaned.get("accessible_branches")
        if not primary:
            self.add_error("primary_branch", "Select the staff member's branch.")
        if role == User.Role.FINANCE_ADMIN and not accessible:
            self.add_error("accessible_branches", "Select at least one branch for this finance user.")
        return cleaned

    def save(self, commit=True):
        profile = super().save(commit=False)
        role = self.cleaned_data["role"]
        primary = self.cleaned_data.get("primary_branch")
        accessible = self.cleaned_data.get("accessible_branches")
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
            role=role,
            branch=primary,
        )
        if role == User.Role.SYSTEM_ADMIN:
            pass
        elif role in (User.Role.STAFF, User.Role.BRANCH_ADMIN):
            user.accessible_branches.set([primary])
        else:
            user.accessible_branches.set(accessible)
        profile.user = user
        if commit:
            profile.save()
        return profile


# ═══════════════════════════════════════════════════════════════
# EDIT FORM (existing staff — no user creation)
# ═══════════════════════════════════════════════════════════════
class StaffProfileForm(forms.ModelForm):
    # Extra fields from the related User model
    first_name = forms.CharField(max_length=150, required=True, widget=_text())
    last_name = forms.CharField(max_length=150, required=False, widget=_text())
    email = forms.EmailField(required=True, widget=_email())

    class Meta:
        model = StaffProfile
        fields = [
            "employee_id", "gender", "date_of_birth", "department",
            "designation", "joining_date", "phone", "emergency_contact",
            "emergency_contact_name", "address", "city", "state",
            "postal_code", "address_proof_type", "address_proof",
            "photo", "is_active",
        ]
        widgets = {
            "employee_id": _text(),
            "gender": _select(),
            "date_of_birth": _date(),
            "department": _select(),
            "designation": _text(),
            "joining_date": _date(),
            "phone": _text(),
            "emergency_contact": _text(),
            "emergency_contact_name": _text(),
            "address": _textarea(),
            "city": _text(),
            "state": _text(),
            "postal_code": _text(),
            "address_proof_type": _text(),
            "address_proof": _file(),
            "photo": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "is_active": _checkbox(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user_id:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        if commit:
            profile.save()
            user = profile.user
            user.first_name = self.cleaned_data["first_name"]
            user.last_name = self.cleaned_data["last_name"]
            user.email = self.cleaned_data["email"]
            user.is_active = profile.is_active
            user.save(update_fields=["first_name", "last_name", "email", "is_active"])
        return profile


# ═══════════════════════════════════════════════════════════════
# SELF EDIT FORM
# ═══════════════════════════════════════════════════════════════
class StaffSelfEditForm(forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = ["phone", "emergency_contact", "emergency_contact_name", "address", "city", "state", "postal_code"]
        widgets = {
            "phone": _text(placeholder="+91 98765 43210"),
            "emergency_contact": _text(placeholder="+91 98765 43210"),
            "emergency_contact_name": _text(placeholder="Emergency contact name"),
            "address": _textarea(placeholder="Full address"),
            "city": _text(placeholder="City"),
            "state": _text(placeholder="State"),
            "postal_code": _text(placeholder="560001"),
        }


# ═══════════════════════════════════════════════════════════════
# EXIT / DEACTIVATE FORM
# ═══════════════════════════════════════════════════════════════
class StaffExitForm(forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = ("leaving_date", "exit_reason")
        widgets = {
            "leaving_date": _date(),
            "exit_reason": _textarea(4, "Resigned, contract ended, etc."),
        }


# ═══════════════════════════════════════════════════════════════
# INLINE FORMS
# ═══════════════════════════════════════════════════════════════
class EducationRecordForm(forms.ModelForm):
    class Meta:
        model = EducationRecord
        fields = ["qualification", "institution", "passing_year", "certificate"]
        widgets = {
            "qualification": _text(placeholder="e.g. B.Ed"),
            "institution": _text(placeholder="University name"),
            "passing_year": _number(placeholder="2020"),
            "certificate": _file(),
        }


class StaffDocumentForm(forms.ModelForm):
    class Meta:
        model = StaffDocument
        fields = ["title", "document_type", "file"]
        widgets = {
            "title": _text(placeholder="Document title"),
            "document_type": _text(placeholder="e.g. ID Proof"),
            "file": _file(),
        }


class SalaryIncrementForm(forms.ModelForm):
    class Meta:
        model = SalaryIncrement
        fields = ["year", "base_salary", "increment_amount", "new_salary"]
        widgets = {
            "year": _number(placeholder="2026"),
            "base_salary": _number(placeholder="50000.00"),
            "increment_amount": _number(placeholder="5000.00"),
            "new_salary": _number(placeholder="55000.00"),
        }


class ExperienceHistoryForm(forms.ModelForm):
    class Meta:
        model = ExperienceHistory
        fields = ["organization", "role", "start_date", "end_date"]
        widgets = {
            "organization": _text(placeholder="Company / School name"),
            "role": _text(placeholder="Previous role"),
            "start_date": _date(),
            "end_date": _date(),
        }


class PromotionHistoryForm(forms.ModelForm):
    class Meta:
        model = PromotionHistory
        fields = ["old_designation", "new_designation", "promotion_date", "remarks"]
        widgets = {
            "old_designation": _text(placeholder="Previous designation"),
            "new_designation": _text(placeholder="New designation"),
            "promotion_date": _date(),
            "remarks": _textarea(2, "Optional remarks"),
        }


# ═══════════════════════════════════════════════════════════════
# FORMSETS
# ═══════════════════════════════════════════════════════════════
EducationFormSet = inlineformset_factory(
    StaffProfile, EducationRecord,
    form=EducationRecordForm,
    extra=1, can_delete=True,
)

DocumentFormSet = inlineformset_factory(
    StaffProfile, StaffDocument,
    form=StaffDocumentForm,
    extra=1, can_delete=True,
)

SalaryFormSet = inlineformset_factory(
    StaffProfile, SalaryIncrement,
    form=SalaryIncrementForm,
    extra=1, can_delete=True,
)

ExperienceFormSet = inlineformset_factory(
    StaffProfile, ExperienceHistory,
    form=ExperienceHistoryForm,
    extra=1, can_delete=True,
)

PromotionFormSet = inlineformset_factory(
    StaffProfile, PromotionHistory,
    form=PromotionHistoryForm,
    extra=1, can_delete=True,
)