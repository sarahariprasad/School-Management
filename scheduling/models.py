from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.mixins import TrackableMixin

SESSION_MINUTES = 60  # every individual therapy session is exactly 1 hour
WEEKDAYS = [(0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun")]
DEFAULT_WEEKDAYS = "0,1,2,3,4"


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LEAVE = "leave", "On Leave"


class TimeSlot(models.Model):
    """A reusable 1-hour slot (e.g. 09:00-10:00)."""
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("start_time",)
        constraints = [
            models.UniqueConstraint(fields=["start_time", "end_time"], name="unique_time_slot")
        ]

    @property
    def duration_minutes(self):
        s = self.start_time.hour * 60 + self.start_time.minute
        e = self.end_time.hour * 60 + self.end_time.minute
        return e - s

    def clean(self):
        if self.start_time and self.end_time and self.duration_minutes != SESSION_MINUTES:
            raise ValidationError(f"A session slot must be exactly {SESSION_MINUTES} minutes.")

    def __str__(self):
        return f"{self.start_time:%I:%M %p} – {self.end_time:%I:%M %p}"


class TherapistSlot(models.Model):
    """The hours a therapist works each day (e.g. 5 of the 8 school slots).
    A therapist with NO rows here is treated as working every active slot."""
    staff = models.ForeignKey(
        "staff.StaffProfile", on_delete=models.CASCADE, related_name="working_slots"
    )
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, related_name="therapist_slots")

    class Meta:
        ordering = ("time_slot__start_time",)
        constraints = [
            models.UniqueConstraint(fields=["staff", "time_slot"], name="unique_therapist_slot")
        ]

    def __str__(self):
        return f"{self.staff.full_name} · {self.time_slot}"


def therapist_works_slot(staff_id, slot_id):
    """True if the therapist works this slot (or has no slots configured)."""
    mine = TherapistSlot.objects.filter(staff_id=staff_id)
    return (not mine.exists()) or mine.filter(time_slot_id=slot_id).exists()


class SlotAssignment(TrackableMixin, models.Model):
    """
    Recurring slot: student + therapy + therapist + 1-hour slot on chosen weekdays.
    Runs from start_date until end_date (blank = continues until the student
    becomes inactive or an admin changes/ends it). Daily TherapySession rows are
    generated from these.
    """
    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, related_name="slot_assignments"
    )
    therapy = models.ForeignKey(
        "students.Therapy", on_delete=models.PROTECT, related_name="slot_assignments"
    )
    staff = models.ForeignKey(
        "staff.StaffProfile", on_delete=models.PROTECT, related_name="slot_assignments"
    )
    time_slot = models.ForeignKey(
        TimeSlot, on_delete=models.PROTECT, related_name="assignments"
    )
    weekdays = models.CharField(max_length=20, default=DEFAULT_WEEKDAYS)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("staff__employee_id", "time_slot__start_time", "student__name")

    @property
    def weekday_list(self):
        return [int(x) for x in self.weekdays.split(",") if x.strip().isdigit()]

    @property
    def weekday_display(self):
        names = dict(WEEKDAYS)
        return ", ".join(names[d] for d in self.weekday_list if d in names)

    @property
    def is_current(self):
        return self.end_date is None or self.end_date >= timezone.localdate()

    def applies_on(self, day):
        return (
            self.start_date <= day
            and (self.end_date is None or day <= self.end_date)
            and day.weekday() in self.weekday_list
        )

    def clean(self):
        if not self.weekday_list:
            raise ValidationError({"weekdays": "Select at least one day."})
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be before the start date."})
        if not (self.student_id and self.staff_id and self.time_slot_id and self.start_date):
            return
        if self._state.adding and not self.student.is_active:
            raise ValidationError({"student": "This student is inactive."})

        if not therapist_works_slot(self.staff_id, self.time_slot_id):
            raise ValidationError({
                "time_slot": f"{self.staff.full_name} does not work in this slot "
                             f"(see Schedule → Therapist Slots)."
            })
        # A therapist may handle several students in the same slot, but one
        # student can only be in one session at a time.
        mine = set(self.weekday_list)
        others = SlotAssignment.objects.exclude(pk=self.pk).filter(
            student_id=self.student_id, time_slot_id=self.time_slot_id
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=self.start_date))
        if self.end_date:
            others = others.filter(start_date__lte=self.end_date)
        for o in others.select_related("staff__user", "therapy"):
            if mine & set(o.weekday_list):
                raise ValidationError({
                    "time_slot": f"{self.student.name} already has {o.therapy} with "
                                 f"{o.staff.full_name} in this slot on overlapping days."
                })

    def __str__(self):
        return f"{self.student.student_id} · {self.therapy} · {self.staff.full_name} · {self.time_slot}"


class TherapySession(TrackableMixin, models.Model):
    """One student + one therapist + one 1-hour slot on one date.
    (A therapist can have several students in the same slot.)"""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        STUDENT_ABSENT = "student_absent", "Student Absent"
        STAFF_ABSENT = "staff_absent", "Therapist Absent"
        CANCELLED = "cancelled", "Cancelled"

    # A therapist can handle many students in one slot. A student can only be
    # in one session per slot; if the therapist is absent the student is free
    # to be re-booked elsewhere.
    STUDENT_BUSY = ["scheduled", "completed", "student_absent"]

    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, related_name="therapy_slots"
    )
    therapy = models.ForeignKey(
        "students.Therapy", on_delete=models.PROTECT, related_name="scheduled_sessions"
    )
    staff = models.ForeignKey(
        "staff.StaffProfile", on_delete=models.PROTECT, related_name="scheduled_sessions"
    )
    date = models.DateField(default=timezone.localdate)
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.PROTECT, related_name="sessions")
    assignment = models.ForeignKey(
        SlotAssignment, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    absence_reason = models.CharField(max_length=255, blank=True)
    auto_marked = models.BooleanField(default=False, help_text="Set automatically from daily attendance.")
    notes = models.TextField(blank=True)
    rescheduled_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="rescheduled_to"
    )

    class Meta:
        ordering = ("date", "time_slot__start_time")
        indexes = [models.Index(fields=["date", "time_slot"])]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "date", "time_slot"],
                condition=Q(status__in=["scheduled", "completed", "student_absent"]),
                name="unique_student_slot_booking",
            ),
            models.UniqueConstraint(
                fields=["assignment", "date"],
                condition=Q(assignment__isnull=False),
                name="unique_assignment_session_day",
            ),
        ]

    BADGES = {
        "scheduled": "primary",
        "completed": "success",
        "student_absent": "warning text-dark",
        "staff_absent": "danger",
        "cancelled": "secondary",
    }

    @property
    def badge_class(self):
        return self.BADGES.get(self.status, "secondary")

    def clean(self):
        if not (self.student_id and self.staff_id and self.date and self.time_slot_id):
            return
        others = TherapySession.objects.exclude(pk=self.pk).filter(
            date=self.date, time_slot_id=self.time_slot_id
        )
        if self.status in self.STUDENT_BUSY and others.filter(
            student_id=self.student_id, status__in=self.STUDENT_BUSY
        ).exists():
            raise ValidationError({"student": "This student already has a session in this slot."})

        if self.status == self.Status.SCHEDULED:
            slot = self.time_slot
            group_id = self.student.group_id
            if group_id and GroupSession.objects.filter(
                group_id=group_id, date=self.date,
                start_time__lt=slot.end_time, end_time__gt=slot.start_time,
            ).exclude(status=GroupSession.Status.CANCELLED).exists():
                raise ValidationError(
                    {"time_slot": "The student's group has a group session at this time."}
                )
            if self.pk is None:
                if not therapist_works_slot(self.staff_id, self.time_slot_id):
                    raise ValidationError({"time_slot": "This therapist does not work in this slot."})
                if StaffAttendance.objects.filter(
                    staff_id=self.staff_id, date=self.date
                ).exclude(status=AttendanceStatus.PRESENT).exists():
                    raise ValidationError({"staff": "Therapist is marked absent/on leave on this date."})
                if StudentAttendance.objects.filter(
                    student_id=self.student_id, date=self.date
                ).exclude(status=AttendanceStatus.PRESENT).exists():
                    raise ValidationError({"student": "Student is marked absent/on leave on this date."})
                from students.models import StudentTherapy
                if not StudentTherapy.objects.filter(
                    student_id=self.student_id, therapy_id=self.therapy_id, is_active=True
                ).exists():
                    raise ValidationError(
                        {"therapy": "Student is not enrolled in this therapy (add it in StudentTherapy first)."}
                    )

    def __str__(self):
        return f"{self.student.student_id} · {self.therapy} · {self.date} {self.time_slot}"


class StudentAttendance(TrackableMixin, models.Model):
    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, related_name="attendance_records"
    )
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=10, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT
    )
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(fields=["student", "date"], name="unique_student_attendance_day")
        ]

    def __str__(self):
        return f"{self.student.student_id} {self.date} {self.status}"


class StaffAttendance(TrackableMixin, models.Model):
    staff = models.ForeignKey(
        "staff.StaffProfile", on_delete=models.CASCADE, related_name="attendance_records"
    )
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=10, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT
    )
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(fields=["staff", "date"], name="unique_staff_attendance_day")
        ]

    def __str__(self):
        return f"{self.staff.employee_id} {self.date} {self.status}"


class GroupSession(TrackableMixin, models.Model):
    """Daily group activity hours for a Group (all students in it attend)."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    group = models.ForeignKey("students.Group", on_delete=models.CASCADE, related_name="group_sessions")
    date = models.DateField(default=timezone.localdate)
    start_time = models.TimeField()
    end_time = models.TimeField()
    staff = models.ForeignKey(
        "staff.StaffProfile", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="group_sessions",
    )
    activity = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("-date", "start_time")

    def clean(self):
        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValidationError({"end_time": "End time must be after start time."})
            if self.group_id and self.date and GroupSession.objects.exclude(pk=self.pk).filter(
                group_id=self.group_id, date=self.date,
                start_time__lt=self.end_time, end_time__gt=self.start_time,
            ).exclude(status=self.Status.CANCELLED).exists():
                raise ValidationError("This group already has a session overlapping this time.")

    def __str__(self):
        return f"{self.group} · {self.date} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class GroupSessionAttendance(models.Model):
    group_session = models.ForeignKey(GroupSession, on_delete=models.CASCADE, related_name="attendance")
    student = models.ForeignKey("students.Student", on_delete=models.CASCADE, related_name="group_attendance")
    status = models.CharField(
        max_length=10, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT
    )
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group_session", "student"], name="unique_group_session_student")
        ]

    def __str__(self):
        return f"{self.student.student_id} {self.status}"
