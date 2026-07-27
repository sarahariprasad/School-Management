from django import forms
from .models import Branch


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ("code", "name", "address", "phone", "email", "is_active")
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}
