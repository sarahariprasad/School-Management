from django import forms
from .models import Branch


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ("code", "name", "address", "phone", "email", "is_active")
        widgets = {
            "code": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. BR001",
            }),
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Branch name",
            }),
            "address": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Full address",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "+91 98765 43210",
                "type": "tel",
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "branch@example.com",
                "type": "email",
            }),
            "is_active": forms.CheckboxInput(attrs={
                "class": "form-check-input",
            }),
        }
        error_messages = {
            "code": {
                "unique": "A branch with this code already exists.",
            },
        }