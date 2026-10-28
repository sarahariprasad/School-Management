from datetime import time

from django.core.management.base import BaseCommand

from scheduling.models import TimeSlot


class Command(BaseCommand):
    help = "Create default 1-hour slots (09-13 and 14-17). Edit in admin afterwards."

    def handle(self, *args, **opts):
        for h in [9, 10, 11, 12, 14, 15, 16]:
            _, created = TimeSlot.objects.get_or_create(
                start_time=time(h, 0), end_time=time(h + 1, 0)
            )
            self.stdout.write(f"{'created' if created else 'exists '} {h}:00")
