from django.db import models
from django.conf import settings
import copy
import logging

from audit_log.services import log_audit, snapshot_instance, build_field_changes

logger = logging.getLogger(__name__)

class TrackableMixin(models.Model):
    """
    Add created_by / updated_by / created_at / updated_at to any model.
    Must inherit BEFORE models.Model:
        class StaffProfile(TrackableMixin, models.Model):

    This is now also the tracking mixin used by fee_payment.models (it used
    to define its own local UserTrackingModel with an identical shape but
    related_name='+' — replaced so there's one tracking mixin app-wide).
    related_name="%(class)s_created" / "%(class)s_updated" avoids reverse
    accessor clashes automatically per concrete model, so no two models
    sharing this mixin will ever collide.
    """
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="%(class)s_created",
        verbose_name="Created By",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="%(class)s_updated",
        verbose_name="Last Updated By",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @property
    def created_by_display(self):
        if self.created_by:
            return self.created_by.get_full_name() or self.created_by.email
        return "System"

    @property
    def updated_by_display(self):
        if self.updated_by:
            return self.updated_by.get_full_name() or self.updated_by.email
        return "System"

class UserTrackingMixin:
    """
    Stamps created_by / updated_by on the model instance from request.user.
    Requires the model to inherit TrackableMixin (above).
    """

    def _stamp_created(self, instance):
        if hasattr(instance, "created_by_id"):
            instance.created_by = self.request.user
        if hasattr(instance, "updated_by_id"):
            instance.updated_by = self.request.user

    def _stamp_updated(self, instance):
        if hasattr(instance, "updated_by_id"):
            instance.updated_by = self.request.user


class AuditableCreateMixin(UserTrackingMixin):
    """Stamp created_by/updated_by, save, then write a CREATE audit row."""

    def form_valid(self, form):
        self._stamp_created(form.instance)
        response = super().form_valid(form)
        try:
            log_audit(
                self.request.user,
                self.object,
                "CREATE",
                snapshot=snapshot_instance(self.object),
            )
        except Exception as e:
            logger.exception("Audit log (CREATE) failed for %s: %s", self.object, e)
        return response


class AuditableUpdateMixin(UserTrackingMixin):
    """
    Capture a pre-save copy of the object (for diffing), stamp updated_by,
    save, then write an UPDATE audit row with only the fields that changed.
    """

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        # Deepcopy so later mutation of obj (by the form) doesn't also
        # mutate our "before" snapshot.
        self._pre_save_instance = copy.deepcopy(obj)
        return obj

    def form_valid(self, form):
        self._stamp_updated(form.instance)
        response = super().form_valid(form)
        try:
            changes = build_field_changes(self._pre_save_instance, self.object)
            if changes:
                log_audit(self.request.user, self.object, "UPDATE", field_changes=changes)
        except Exception as e:
            logger.exception("Audit log (UPDATE) failed for %s: %s", self.object, e)
        return response


class AuditableDeleteMixin:
    """Write a DELETE audit row (with a snapshot) before the row disappears."""

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            log_audit(
                request.user,
                self.object,
                "DELETE",
                snapshot=snapshot_instance(self.object),
            )
        except Exception as e:
            logger.exception("Audit log (DELETE) failed for %s: %s", self.object, e)
        return super().delete(request, *args, **kwargs)


class AuditableFormsetMixin:
    """
    For views that save an inline formset directly (bypassing form_valid on
    a single ModelForm) — call self.log_formset(formset, parent_instance)
    after formset.save().
    """

    def log_formset(self, formset, parent_instance, parent_name="staff"):
        from audit_log.services import log_formset_changes
        try:
            log_formset_changes(self.request.user, formset, parent_instance, parent_name=parent_name)
        except Exception as e:
            logger.exception("Audit log (formset) failed for %s: %s", parent_instance, e)