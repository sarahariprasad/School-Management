from django import template

from scheduling.access import has_schedule_access

register = template.Library()


@register.filter
def can_schedule(user):
    """{% if user|can_schedule %} ... {% endif %}  (same rule the views enforce)."""
    return has_schedule_access(user)
