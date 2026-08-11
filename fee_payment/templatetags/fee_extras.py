from django import template
from fee_payment.helpers import get_student_display_id, get_student_id_field_name

register = template.Library()


@register.filter
def student_id(student):
    """Return the best available identifier for a student."""
    if not student:
        return ""
    return get_student_display_id(student)


@register.filter
def student_id_label(default_label="ID"):
    """Return the label for the student identifier field."""
    field = get_student_id_field_name()
    if field:
        return field.replace('_', ' ').title()
    return default_label