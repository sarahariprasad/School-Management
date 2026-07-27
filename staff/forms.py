from django import forms
from accounts.models import User
from branches.models import Branch
from django.forms import inlineformset_factory
from .models import EducationRecord, StaffDocument, StaffProfile,ExperienceHistory,PromotionHistory,SalaryIncrement

class StaffCreateForm(forms.ModelForm):
    email = forms.EmailField(help_text="This becomes the staff member's login username.")
    password = forms.CharField(widget=forms.PasswordInput, min_length=8)
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    role = forms.ChoiceField(choices=User.Role.choices, initial=User.Role.STAFF)
    primary_branch = forms.ModelChoiceField(
        queryset=Branch.objects.filter(is_active=True), required=True,
        help_text="Home branch for the staff record. System admins still have access to every branch."
    )
    accessible_branches = forms.ModelMultipleChoiceField(
        queryset=Branch.objects.filter(is_active=True), required=False,
        help_text="Only needed for Finance admin. System admins automatically access all branches."
    )

    class Meta:
        model = StaffProfile
        fields = ("employee_id", "department", "designation", "joining_date", "phone", "address", "city", "state", "postal_code", "address_proof_type", "address_proof", "is_active")
        widgets = {"joining_date": forms.DateInput(attrs={"type": "date"})}

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
        email = self.cleaned_data["email"].lower()
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
            email=self.cleaned_data["email"], password=self.cleaned_data["password"],
            first_name=self.cleaned_data["first_name"], last_name=self.cleaned_data["last_name"],
            role=role, branch=primary,
        )
        if role == User.Role.SYSTEM_ADMIN:
            # System admins are intentionally unrestricted by branch_scope.
            pass
        elif role in (User.Role.STAFF, User.Role.BRANCH_ADMIN):
            user.accessible_branches.set([primary])
        else:
            user.accessible_branches.set(accessible)
        profile.user = user
        if commit:
            profile.save()
        return profile


class StaffExitForm(forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = ("leaving_date", "exit_reason")
        widgets = {
            "leaving_date": forms.DateInput(attrs={"type": "date"}),
            "exit_reason": forms.Textarea(attrs={"rows": 4, "placeholder": "Resigned, contract ended, etc."}),
        }

class StaffProfileForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    class Meta:
        model = StaffProfile
        fields = [
            "employee_id",
            "department",
            "designation",
            "joining_date",
            
            "phone",
            "address",
            "city",
            "state",
            "postal_code",
            "address_proof_type",
            "address_proof",
            "is_active",
        ]
        widgets = {
            "joining_date": forms.DateInput(attrs={"type": "date"})
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user_id:
            self.fields["email"].initial = self.instance.user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        if commit:
            profile.save()
            user = profile.user
            user.email = self.cleaned_data["email"]
            # Keep login access in sync with the "Active" flag on this form.
            # Without this, an admin can mark a profile inactive/active here
            # while the underlying login (User.is_active) silently stays
            # out of sync with what staff_deactivate() does.
            user.is_active = profile.is_active
            user.save(update_fields=["email", "is_active"])
        return profile

class EducationRecordForm(forms.ModelForm):
    class Meta:
        model = EducationRecord
        fields = ["qualification", "institution", "passing_year", "certificate"]

class StaffDocumentForm(forms.ModelForm):
    class Meta:
        model = StaffDocument
        fields = ["title", "document_type", "file"]

class SalaryIncrementForm(forms.ModelForm):
    class Meta:
        model = SalaryIncrement
        fields = ["year", "base_salary", "increment_amount", "new_salary"]
class ExperienceHistoryForm(forms.ModelForm):
    class Meta:
        model = ExperienceHistory
        fields = ["organization", "role", "start_date", "end_date"]

# Inline formsets
EducationFormSet = inlineformset_factory(StaffProfile, EducationRecord, form=EducationRecordForm, extra=1, can_delete=True)
DocumentFormSet = inlineformset_factory(StaffProfile, StaffDocument, form=StaffDocumentForm, extra=1, can_delete=True)
SalaryFormSet = inlineformset_factory(StaffProfile, SalaryIncrement, form=SalaryIncrementForm, extra=1, can_delete=True)
ExperienceFormSet = inlineformset_factory(StaffProfile, ExperienceHistory, form=ExperienceHistoryForm, extra=1, can_delete=True)

class StaffSelfEditForm(forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = ["address", "phone"]  # only these fields are editable


class PromotionHistoryForm(forms.ModelForm):
    class Meta:
        model = PromotionHistory
        fields = ["old_designation", "new_designation", "promotion_date"]

