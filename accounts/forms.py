from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, UserChangeForm
from .models import User


class EmailAuthenticationForm(AuthenticationForm):
    """
    Login form that treats the 'username' field as an email address.
    Renders with Bootstrap form-control styling.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email Address"
        self.fields["username"].widget = forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "you@example.com",
            "autocomplete": "email",
            "autofocus": True,
        })
        self.fields["password"].widget = forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your password",
            "autocomplete": "current-password",
        })


class UserCreateForm(UserCreationForm):
    """Form for creating a new user (admin/staff use)."""

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "branch", "accessible_branches", "is_active")
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "user@example.com"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "branch": forms.Select(attrs={"class": "form-select"}),
            "accessible_branches": forms.SelectMultiple(attrs={"class": "form-select", "size": "4"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class UserUpdateForm(UserChangeForm):
    """Form for editing an existing user (admin/staff use)."""
    password = None  # Hide password field; use separate password change flow

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "branch", "accessible_branches", "is_active")
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "branch": forms.Select(attrs={"class": "form-select"}),
            "accessible_branches": forms.SelectMultiple(attrs={"class": "form-select", "size": "4"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }