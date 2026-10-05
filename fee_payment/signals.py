"""
Django signals for the fee payment system.

All heavy / side-effect work (installment generation, notifications)
is deferred with transaction.on_commit() so it only runs if the DB
transaction actually succeeds.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction

from .models import StudentFeeAssignment, FeePayment
from .notifications import (
    send_fee_due_notification,
    send_payment_recorded_notification
)

logger = logging.getLogger(__name__)


# ---------- StudentFeeAssignment Signals ----------

@receiver(post_save, sender=StudentFeeAssignment)
def handle_assignment_created(sender, instance, created, **kwargs):
    """
    Auto-generate installments and notify parent when a new fee assignment is created.
    """
    if not created:
        return

    # Defer until transaction commits to avoid running on rollback
    def _on_commit():
        try:
            instance.generate_installments()
            logger.info("Installments generated for assignment %s.", instance.pk)
        except Exception as e:
            logger.exception("Installment generation failed for assignment %s: %s", instance.pk, e)
            return

        # Send fee due notification (non-blocking; failures are logged internally)
        try:
            send_fee_due_notification(instance)
        except Exception as e:
            logger.exception("Fee due notification failed for assignment %s: %s", instance.pk, e)

    transaction.on_commit(_on_commit)


# Payment confirmations are deliberately dispatched from the model-save
# signal rather than the view. This gives admin/API-created payments the same
# behaviour and ensures the message is sent only after a successful commit.
@receiver(post_save, sender=FeePayment)
def handle_payment_recorded(sender, instance, created, **kwargs):
    if not created:
        return

    def _on_commit():
        try:
            send_payment_recorded_notification(instance)
        except Exception as e:
            logger.exception("Payment notification failed for payment %s: %s", instance.pk, e)

    transaction.on_commit(_on_commit)
