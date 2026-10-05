"""
Audit Log App — Tracks every create, update, delete across any model.
Uses Django's ContentTypes for generic relations (works with Staff, Student, etc.)
"""
import json
from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("CREATE", "Created"),
        ("UPDATE", "Updated"),
        ("DELETE", "Deleted"),
    ]

    # ── Who performed the action ──
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="Action By",
    )

    # ── What happened ──
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    action_time = models.DateTimeField(auto_now_add=True)

    # ── Which object was affected (Generic Foreign Key) ──
    # This lets one AuditLog table track changes on Staff, Student, Branch, etc.
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    # ── Human-readable details ──
    object_repr = models.CharField(
        max_length=255,
        help_text="Human-readable name of the object at the time of change"
    )

    # ── Field-level changes (stored as JSON) ──
    # Example: {"phone": {"old": "9876543210", "new": "9876543211"}, "city": {"old": "Delhi", "new": "Mumbai"}}
    field_changes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Dictionary of changed fields with old/new values"
    )

    # ── Optional: store the full snapshot (for complex cases) ──
    snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full object snapshot after the change (optional)"
    )

    class Meta:
        ordering = ["-action_time"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["content_type", "object_id", "-action_time"]),
            models.Index(fields=["user", "-action_time"]),
            models.Index(fields=["action", "-action_time"]),
        ]

    def __str__(self):
        user_name = self.user_display
        return f"{user_name} {self.get_action_display().lower()} {self.object_repr}"

    @property
    def user_display(self):
        """Return full name or email of the user who performed the action."""
        if self.user:
            return self.user.get_full_name() or self.user.email
        return "System"

    @property
    def changed_fields(self):
        """Return list of field names that were modified."""
        return list(self.field_changes.keys())

    @property
    def changed_fields_count(self):
        return len(self.changed_fields)

    @property
    def action_icon(self):
        """Return Bootstrap icon class for the action type."""
        icons = {
            "CREATE": "bi-plus-circle",
            "UPDATE": "bi-pencil-square",
            "DELETE": "bi-trash",
        }
        return icons.get(self.action, "bi-question-circle")

    @property
    def action_color(self):
        """Return Bootstrap color class for the action type."""
        colors = {
            "CREATE": "success",
            "UPDATE": "warning",
            "DELETE": "danger",
        }
        return colors.get(self.action, "secondary")