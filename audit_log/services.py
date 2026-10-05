"""
Audit logging helpers for the audit_log app.
Drop this into your audit_log app as services.py
"""
from django.contrib.contenttypes.models import ContentType
from .models import AuditLog



def log_audit(user, instance, action, field_changes=None, snapshot=None):
    """
    Create an AuditLog entry for any model instance.

    Args:
        user: The user performing the action
        instance: The model instance being changed
        action: 'CREATE', 'UPDATE', or 'DELETE'
        field_changes: Optional dict of {field: {old, new}}
        snapshot: Optional full snapshot dict
    """
    if not instance or not instance.pk:
        return  # Cannot log unsaved instances

    ct = ContentType.objects.get_for_model(instance)
    AuditLog.objects.create(
        user=user,
        action=action,
        content_type=ct,
        object_id=instance.pk,
        object_repr=str(instance),
        field_changes=field_changes or {},
        snapshot=snapshot or {},
    )


def snapshot_instance(instance, exclude=None):
    """
    Create a JSON-serializable snapshot of a model instance's non-relation fields.
    """
    exclude = set(exclude or []) | {"id", "pk"}
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in exclude or field.is_relation:
            continue
        val = getattr(instance, field.attname, None)
        data[field.name] = str(val) if val is not None else None
    return data


def build_field_changes(old_instance, new_instance, exclude=None):
    """
    Compare two model instances and return a dict of changed fields.
    old_instance should be a fresh DB copy captured BEFORE the form save.
    """
    exclude = set(exclude or []) | {
        "created_at", "updated_at", "created_by", "updated_by", "id", "pk"
    }
    changes = {}
    for field in old_instance._meta.concrete_fields:
        name = field.name
        if name in exclude or field.is_relation:
            continue
        old_val = getattr(old_instance, field.attname, None)
        new_val = getattr(new_instance, field.attname, None)
        if old_val != new_val:
            changes[name] = {
                "old": str(old_val) if old_val is not None else None,
                "new": str(new_val) if new_val is not None else None,
            }
    return changes


def log_formset_changes(user, formset, parent_instance, parent_name="staff"):
    """
    Log CREATE / UPDATE / DELETE for an inline formset.
    Call this AFTER formset.save() has already been executed.
    """
    for form in formset.forms:
        is_delete = form.cleaned_data.get("DELETE")
        instance = form.instance

        # ── Deletion ──
        if is_delete and instance.pk:
            log_audit(
                user,
                instance,
                "DELETE",
                snapshot={"deleted_from": parent_name, "object_id": instance.pk},
            )
            continue

        if not instance.pk:
            continue

        is_initial = form in formset.initial_forms

        # ── New instance (extra form that got saved) ──
        if not is_initial:
            log_audit(user, instance, "CREATE", snapshot=snapshot_instance(instance))

        # ── Existing instance that was modified ──
        elif form.changed_data:
            changes = {}
            for field_name in form.changed_data:
                if field_name in ("id", "pk", parent_name.lower(), "staff"):
                    continue
                initial = form.initial.get(field_name)
                new_val = form.cleaned_data.get(field_name)
                # Normalise file fields to file names
                if hasattr(initial, "name"):
                    initial = initial.name
                if hasattr(new_val, "name"):
                    new_val = new_val.name
                if initial != new_val:
                    changes[field_name] = {
                        "old": str(initial) if initial is not None else None,
                        "new": str(new_val) if new_val is not None else None,
                    }
            if changes:
                log_audit(user, instance, "UPDATE", field_changes=changes)