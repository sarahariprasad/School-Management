# students/models.py
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from branches.models import Branch  # import your branch model
from staff.models import StaffProfile   # import your staff model
from core.mixins import TrackableMixin


def student_document_path(instance, filename):
    student_id = getattr(instance, "student_id", None) or instance.pk or "new"
    return f"students/{student_id}/{filename}"


def validate_document_size(file):
    if file.size > 10 * 1024 * 1024:  # 10 MB limit
        raise ValidationError("Document size must not exceed 10 MB.")


student_document_validators = [
    FileExtensionValidator(["pdf", "jpg", "jpeg", "png"]),
    validate_document_size,
]


class Group(models.Model):
    

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)

    def get_name_display(self):
        return self.name.title()

    def __str__(self):
        return self.get_name_display()


class GroupStaffAssignment(models.Model):
    """Multiple staff can be assigned to a group; a staff member can also
    cover more than one group, so this is a proper through-model, not a
    single FK on either side."""
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="staff_assignments")
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="group_assignments")
    is_active = models.BooleanField(default=True)
    assigned_on = models.DateField(default=timezone.now)
    ended_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("-assigned_on",)
        constraints = [
            models.UniqueConstraint(
                fields=["group", "staff"],
                condition=models.Q(is_active=True),
                name="unique_active_group_staff",
            )
        ]

    def __str__(self):
        return f"{self.staff.full_name} — {self.group}"


class Therapy(models.Model):
    """Therapy options like Speech Therapy, Occupational Therapy, ABA, etc."""
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Student(TrackableMixin, models.Model):
    student_id = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=[("Male", "Male"), ("Female", "Female")])

    # Group — replaces the old "class" concept. One group per student.
    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students",
    )
    student_branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)

    # Active status
    is_active = models.BooleanField(default=True, help_text="Mark student as active or inactive")
    inactive_date = models.DateField(null=True, blank=True, help_text="Date when student became inactive")

    # Therapies — many therapies per student, each with its own therapist/schedule.
    therapies = models.ManyToManyField(Therapy, through="StudentTherapy", blank=True, related_name="students")

    # Parent details
    mother_name = models.CharField(max_length=100)
    father_name = models.CharField(max_length=100)
    mother_phone = models.CharField(max_length=15, blank=True, null=True)
    father_phone = models.CharField(max_length=15, blank=True, null=True)
    mother_email = models.EmailField(blank=True, null=True)
    father_email = models.EmailField(blank=True, null=True)
    mother_occupation = models.CharField(max_length=100, blank=True, null=True)
    father_occupation = models.CharField(max_length=100, blank=True, null=True)

    # Photos (use FileField instead of ImageField to avoid Pillow)
    mother_photo = models.FileField(
        upload_to=student_document_path, blank=True, null=True, validators=student_document_validators
    )
    father_photo = models.FileField(
        upload_to=student_document_path, blank=True, null=True, validators=student_document_validators
    )
    photo = models.FileField(
        upload_to=student_document_path, blank=True, null=True, validators=student_document_validators
    )

    # Medical documents
    medical_documents = models.FileField(
        upload_to=student_document_path, blank=True, null=True, validators=student_document_validators
    )

    # Address
    address = models.TextField()

    admission_date = models.DateField(auto_now_add=True)
    # created_at / updated_at / created_by / updated_by provided by TrackableMixin

    class Meta:
        ordering = ["-admission_date"]

    def __str__(self):
        return f"{self.student_id} — {self.name}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # remember the DB state so save() can detect what actually changed
        self._original_is_active = self.is_active
        self._original_group_id = self.group_id

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        status_changed = (not is_new) and (self.is_active != self._original_is_active)
        group_changed = (not is_new) and (self.group_id != self._original_group_id)

        # keep inactive_date consistent with is_active automatically
        if status_changed and not self.is_active and not self.inactive_date:
            self.inactive_date = timezone.now().date()
        if status_changed and self.is_active:
            self.inactive_date = None

        super().save(*args, **kwargs)

        # log every status change (including the very first save) into StatusHistory
        if is_new:
            StatusHistory.objects.create(
                student=self,
                status="active" if self.is_active else "inactive",
                changed_on=self.admission_date or timezone.now().date(),
            )
        elif status_changed:
            StatusHistory.objects.create(
                student=self,
                status="active" if self.is_active else "inactive",
                changed_on=self.inactive_date or timezone.now().date(),
            )

        # log every group assignment (including the initial one at admission) into GroupHistory
        if is_new:
            GroupHistory.objects.create(
                student=self,
                group=self.group,
                changed_on=self.admission_date or timezone.now().date(),
                reason="Admission",
            )
        elif group_changed:
            GroupHistory.objects.create(
                student=self,
                group=self.group,
                changed_on=timezone.now().date(),
            )

        self._original_is_active = self.is_active
        self._original_group_id = self.group_id

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = timezone.now().date()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )


class StudentTherapy(models.Model):
    """Through-model for Student <-> Therapy. Each row is one therapy
    enrollment for a student, with its own assigned therapist and schedule —
    this is what actually lets a student 'take multiple therapies'."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="therapy_enrollments")
    therapy = models.ForeignKey(Therapy, on_delete=models.CASCADE, related_name="enrollments")
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="therapy_sessions"
    )
    frequency = models.CharField(max_length=50, blank=True, help_text="e.g. '3x/week'")
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-start_date",)
        constraints = [
            models.UniqueConstraint(
                fields=["student", "therapy"],
                condition=models.Q(is_active=True),
                name="unique_active_student_therapy",
            )
        ]

    def __str__(self):
        return f"{self.student.student_id} — {self.therapy} ({self.staff.full_name if self.staff else 'unassigned'})"


class StatusHistory(models.Model):
    """Tracks every active/inactive transition for a student, and since when."""
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="status_history")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    changed_on = models.DateField(default=timezone.now)
    reason = models.CharField(max_length=255, blank=True, null=True)
    changed_by = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_on", "-id"]
        verbose_name_plural = "Status histories"

    def __str__(self):
        return f"{self.student.student_id} - {self.status} on {self.changed_on}"


class GroupHistory(models.Model):
    """Tracks every group a student has been placed in, and since when —
    replaces the old ClassHistory. Covers both initial placement and
    later re-grouping (e.g. moving from Orange to Green as needs change)."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="group_history")
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True)
    changed_on = models.DateField(default=timezone.now)
    reason = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="e.g. 'Initial placement', 'Reassessment', 'Progress review'"
    )
    changed_by = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_on", "-id"]
        verbose_name_plural = "Group histories"

    def __str__(self):
        return f"{self.student.student_id} - {self.group} on {self.changed_on}"


REMARK_CATEGORY_CHOICES = [
    ("general", "General"),
    ("academic", "Academic"),
    ("behavior", "Behavior"),
    ("speech_therapy", "Speech Therapy"),
    ("occupational_therapy", "Occupational Therapy"),
    ("physiotherapy", "Physiotherapy"),
    ("other", "Other"),
]


class Remark(models.Model):
    """A single progress note / remark for a student, from admission to leaving.
    Optionally emailed to parents (mother_email / father_email on Student)."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="remarks")
    category = models.CharField(max_length=30, choices=REMARK_CATEGORY_CHOICES, default="general")
    remark_text = models.TextField()
    created_by = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_to_parents = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student.student_id} - {self.category} - {self.created_at:%Y-%m-%d}"
