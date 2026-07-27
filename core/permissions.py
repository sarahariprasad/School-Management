from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Allow Django superusers or users having any of the named roles."""
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser or user.role in roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("You do not have access to this page.")
        return wrapped
    return decorator


def branch_scope(user, queryset, branch_field="branch"):
    """Return permitted records. System admins see all; other users see assigned branches."""
    if user.is_superuser or user.role == user.Role.SYSTEM_ADMIN:
        return queryset
    branch_ids = user.accessible_branches.values_list("id", flat=True)
    if user.branch_id:
        branch_ids = list(branch_ids) + [user.branch_id]
    if not branch_ids:
        return queryset.none()
    return queryset.filter(**{f"{branch_field}__in": branch_ids}).distinct()
