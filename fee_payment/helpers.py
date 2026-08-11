"""
Helper utilities for the fee payment system.
Handles differences in Student model field names across projects.
"""

from django.db.models import Q
from students.models import Student


def _get_student_id_field():
    """
    Detect the student identifier field name.
    Tries common field names in order of preference.
    Returns the first matching field name, or None if no identifier found.
    """
    candidates = [
        'roll_no',
        'roll_number',
        'registration_no',
        'registration_number',
        'student_id',
        'enrollment_no',
        'enrollment_number',
        'admission_no',
        'admission_number',
    ]
    for field_name in candidates:
        try:
            Student._meta.get_field(field_name)
            return field_name
        except:
            continue
    return None


# Cache the result so we only check once
_STUDENT_ID_FIELD = _get_student_id_field()


def get_student_id_field_name():
    """Return the detected student identifier field name."""
    return _STUDENT_ID_FIELD


def build_student_search_filter(search_value):
    """
    Build a Q filter for searching students by name OR identifier.
    Safe to use even if the Student model has no identifier field.
    """
    filters = Q(student__name__icontains=search_value)

    if _STUDENT_ID_FIELD:
        filters |= Q(**{f'student__{_STUDENT_ID_FIELD}__icontains': search_value})

    return filters


def build_student_search_filter_installment(search_value):
    """
    Build a Q filter for searching installments by student name OR identifier.
    """
    filters = Q(assignment__student__name__icontains=search_value)

    if _STUDENT_ID_FIELD:
        filters |= Q(**{f'assignment__student__{_STUDENT_ID_FIELD}__icontains': search_value})

    return filters


def build_student_search_filter_payment(search_value):
    """
    Build a Q filter for searching payments by student name OR identifier.
    """
    filters = Q(installment__assignment__student__name__icontains=search_value)

    if _STUDENT_ID_FIELD:
        filters |= Q(**{f'installment__assignment__student__{_STUDENT_ID_FIELD}__icontains': search_value})

    return filters


def get_student_display_id(student):
    """
    Get the best available identifier for a student object.
    Returns the identifier value, or the student's PK as fallback.
    """
    if _STUDENT_ID_FIELD:
        val = getattr(student, _STUDENT_ID_FIELD, None)
        if val:
            return val
    return student.pk