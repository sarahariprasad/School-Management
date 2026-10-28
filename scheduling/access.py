from django.conf import settings

ADMIN_ROLES = {"SYSTEM_ADMIN", "BRANCH_ADMIN", "FINANCE_ADMIN"}


def has_schedule_access(user):
    """Scheduling is for administrators only. Staff-profile (therapist / staff)
    logins can neither see the menu nor open the pages.
    Override with SCHEDULING_ALLOWED_ROLES = ["SYSTEM_ADMIN", ...] in settings.py."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    allowed = set(getattr(settings, "SCHEDULING_ALLOWED_ROLES", ADMIN_ROLES))
    return getattr(user, "role", None) in allowed
