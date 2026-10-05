"""
Django Admin configuration for Audit Logs.
Read-only — admins can view but not modify audit entries.
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = [
        "action_time",
        "user_link",
        "action_badge",
        "content_type",
        "object_repr",
        "changed_fields_count",
    ]
    list_filter = [
        "action",
        "content_type",
        ("action_time", admin.DateFieldListFilter),
    ]
    search_fields = [
        "user__email",
        "user__first_name",
        "user__last_name",
        "object_repr",
    ]
    readonly_fields = [
        "user",
        "action",
        "action_time",
        "content_type",
        "object_id",
        "object_repr",
        "field_changes_formatted",
        "snapshot",
    ]
    date_hierarchy = "action_time"
    list_per_page = 50

    def user_link(self, obj):
        if obj.user:
            return format_html(
                '<a href="/admin/accounts/user/{}/change/">{}</a>',
                obj.user.pk,
                obj.user_display,
            )
        return "System"
    user_link.short_description = "User"
    user_link.admin_order_field = "user"

    def action_badge(self, obj):
        colors = {"CREATE": "green", "UPDATE": "orange", "DELETE": "red"}
        color = colors.get(obj.action, "gray")
        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600;">{}</span>',
            color,
            obj.get_action_display(),
        )
    action_badge.short_description = "Action"
    action_badge.admin_order_field = "action"

    def changed_fields_count(self, obj):
        count = obj.changed_fields_count
        if count == 0:
            return "—"
        return format_html(
            '<span style="background:#e0f2fe;color:#0369a1;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600;">{} field{}</span>',
            count,
            "s" if count > 1 else "",
        )
    changed_fields_count.short_description = "Changes"

    def field_changes_formatted(self, obj):
        if not obj.field_changes:
            return "No field changes recorded"
        rows = []
        for field, change in obj.field_changes.items():
            old_val = change.get("old") or "<em>empty</em>"
            new_val = change.get("new") or "<em>empty</em>"
            rows.append(
                f'<div style="margin-bottom:8px;padding:8px 12px;background:#f8fafc;border-radius:8px;border-left:3px solid #0f766e;">'
                f'<strong style="color:#0f172a;">{field.title()}</strong><br>'
                f'<span style="color:#dc2626;text-decoration:line-through;">{old_val}</span> '
                f'<span style="color:#94a3b8;">→</span> '
                f'<span style="color:#16a34a;font-weight:600;">{new_val}</span>'
                f'</div>'
            )
        return format_html("".join(rows))
    field_changes_formatted.short_description = "Field Changes"

    def has_add_permission(self, request):
        return False  # Audit logs should never be manually created

    def has_change_permission(self, request, obj=None):
        return False  # Audit logs are immutable

    def has_delete_permission(self, request, obj=None):
        # Only superusers can delete audit logs (and rarely should)
        return request.user.is_superuser