"""
One-off repair: recalculate FeeInstallment.is_fully_paid from the payments
that actually exist.

Usage:
    python manage.py sync_installment_payment_status

Safe to run any time. It only corrects rows whose stored flag disagrees with
their real balance (e.g. installments paid under earlier versions of the
code), and prints how many it fixed.
"""

from django.core.management.base import BaseCommand
from fee_payment.models import FeeInstallment


class Command(BaseCommand):
    help = "Recalculate FeeInstallment.is_fully_paid from actual payments."

    def handle(self, *args, **options):
        total = FeeInstallment.objects.count()
        corrected = FeeInstallment.resync_paid_flags()
        self.stdout.write(self.style.SUCCESS(
            f"Checked {total} installment(s); corrected {corrected}."
        ))