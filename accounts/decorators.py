"""
Role-based permission decorators for the entire project.

Usage:
    from accounts.decorators import role_required, admin_required, finance_required

    @admin_required
def my_view(request):
        ...
"""

from functools import wraps
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages


def _check_role(user, allowed_roles):
    """Internal helper: returns True if user has one of the allowed roles."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.role in allowed_roles


def role_required(*roles):
    """
    Decorator that restricts a view to users with specific role(s).

    Args:
        roles: One or more User.Role values (e.g., "SYSTEM_ADMIN", "FINANCE_ADMIN")

    Example:
        @role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
        def branch_edit(request, pk):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            if _check_role(request.user, roles):
                return view_func(request, *args, **kwargs)
            messages.error(request, "Access denied. You do not have permission to view this page.")
            return redirect("branch_list")  # Change to your default landing page
        return _wrapped_view
    return decorator


# Convenience decorators for common role combinations

def admin_required(view_func):
    """Restrict to System Admin only."""
    return role_required("SYSTEM_ADMIN")(view_func)


def finance_required(view_func):
    """Restrict to System Admin or Finance Admin."""
    return role_required("SYSTEM_ADMIN", "FINANCE_ADMIN")(view_func)


def branch_admin_required(view_func):
    """Restrict to System Admin, Branch Admin, or Finance Admin."""
    return role_required("SYSTEM_ADMIN", "BRANCH_ADMIN", "FINANCE_ADMIN")(view_func)


def staff_required(view_func):
    """Allow any authenticated staff-level user (all roles)."""
    return role_required("SYSTEM_ADMIN", "FINANCE_ADMIN", "BRANCH_ADMIN", "STAFF")(view_func)