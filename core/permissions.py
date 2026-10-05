import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

logger = logging.getLogger(__name__)


def role_required(*roles):
    """Allow Django superusers or users having any of the named roles.
    Unauthorized attempts are logged and redirected with a message
    instead of raising a raw 403."""
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser or user.role in roles:
                return view_func(request, *args, **kwargs)

            logger.warning(
                "Permission denied: user=%s (role=%s) tried to access %s (requires one of %s)",
                user.username, getattr(user, "role", None), request.path, roles,
            )
            messages.error(request, "You do not have permission to access this page.")
            return redirect("student_list")
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