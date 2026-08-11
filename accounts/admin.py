from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .forms import UserCreateForm, UserUpdateForm
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    add_form = UserCreateForm
    form = UserUpdateForm

    list_display = (
        "email",
        "first_name",
        "last_name",
        "role",
        "branch",
        "is_active",
        "date_joined",
    )
    list_filter = ("role", "branch", "is_active", "date_joined")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    readonly_fields = ("last_login", "date_joined")

    fieldsets = (
        (None, {
            "fields": ("email", "password"),
        }),
        ("Personal Info", {
            "fields": ("first_name", "last_name"),
        }),
        ("Access & Permissions", {
            "fields": (
                "role",
                "branch",
                "accessible_branches",
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            ),
        }),
        ("Important Dates", {
            "fields": ("last_login", "date_joined"),
            "classes": ("collapse",),
        }),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "email",
                "password1",
                "password2",
                "first_name",
                "last_name",
                "role",
                "branch",
                "accessible_branches",
                "is_active",
            ),
        }),
    )