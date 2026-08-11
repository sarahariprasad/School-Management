from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models


def staff_document_path(instance, filename):
    staff_id = getattr(instance, "staff_id", None) or instance.pk or "new"
    return f"staff/{staff_id}/{filename}"


def validate_document_size(file):
    if file.size > 10 * 1024 * 1024:
        raise ValidationError("Document size must not exceed 10 MB.")


document_validators = [
    FileExtensionValidator(["pdf", "jpg", "jpeg", "png"]),
    validate_document_size,
]


class StaffProfile(models.Model):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"
        PREFER_NOT = "N", "Prefer not to say"

    class Department(models.TextChoices):
        ACADEMIC = "ACADEMIC", "Academic"
        ADMINISTRATION = "ADMINISTRATION", "Administration"
        FINANCE = "FINANCE", "Finance"
        SUPPORT = "SUPPORT", "Support"

    # ── User Link ──
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )

    # ── Basic Info ──
    employee_id = models.CharField(max_length=30, unique=True, db_index=True)
    gender = models.CharField(
        max_length=1,
        choices=Gender.choices,
        blank=True,
        default="",
    )
    date_of_birth = models.DateField(blank=True, null=True)
    department = models.CharField(max_length=20, choices=Department.choices)
    designation = models.CharField(max_length=100)

    # ── Employment Dates ──
    joining_date = models.DateField()
    leaving_date = models.DateField(null=True, blank=True)
    exit_reason = models.TextField(blank=True)

    # ── Contact ──
    phone = models.CharField(max_length=20, blank=True)
    emergency_contact = models.CharField(max_length=20, blank=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=15, blank=True)

    # ── Documents ──
    address_proof_type = models.CharField(max_length=60, blank=True)
    address_proof = models.FileField(
        upload_to=staff_document_path,
        blank=True,
        validators=document_validators,
    )
    photo = models.ImageField(
        upload_to=staff_document_path,
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png"]),
            validate_document_size,
        ],
    )

    # ── Status ──
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("employee_id",)
        verbose_name = "Staff Profile"
        verbose_name_plural = "Staff Profiles"
        indexes = [
            models.Index(fields=["department", "is_active"]),
            models.Index(fields=["joining_date"]),
        ]

    def __str__(self):
        return f"{self.employee_id} — {self.user.get_full_name() or self.user.email}"

    @property
    def full_name(self):
        # If the queryset annotated this value, return it directly
        if hasattr(self, "_full_name"):
            return self._full_name
        return self.user.get_full_name() or self.user.email

    @full_name.setter
    def full_name(self, value):
        # Allows queryset annotations (e.g. .annotate(full_name=...))
        # to attach a value without raising AttributeError
        self._full_name = value

    @property
    def current_designation(self):
        latest = self.promotions.order_by("-promotion_date").first()
        return latest.new_designation if latest else self.designation


class EducationRecord(models.Model):
    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="education_records",
    )
    qualification = models.CharField(max_length=150)
    institution = models.CharField(max_length=180)
    passing_year = models.PositiveSmallIntegerField()
    certificate = models.FileField(
        upload_to=staff_document_path,
        blank=True,
        validators=document_validators,
    )

    class Meta:
        ordering = ("-passing_year",)
        verbose_name = "Education Record"
        verbose_name_plural = "Education Records"

    def __str__(self):
        return f"{self.qualification} ({self.passing_year})"


class StaffDocument(models.Model):
    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    title = models.CharField(max_length=150)
    document_type = models.CharField(max_length=80, blank=True)
    file = models.FileField(
        upload_to=staff_document_path,
        validators=document_validators,
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-uploaded_at",)
        verbose_name = "Staff Document"
        verbose_name_plural = "Staff Documents"

    def __str__(self):
        return self.title


class ExperienceHistory(models.Model):
    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="experience_history",
    )
    organization = models.CharField(max_length=200)
    role = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)

    class Meta:
        ordering = ("-start_date",)
        verbose_name = "Experience History"
        verbose_name_plural = "Experience Histories"

    def __str__(self):
        return f"{self.role} at {self.organization}"


class PromotionHistory(models.Model):
    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="promotions",
    )
    old_designation = models.CharField(max_length=100)
    new_designation = models.CharField(max_length=100)
    promotion_date = models.DateField()
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ("-promotion_date",)
        verbose_name = "Promotion History"
        verbose_name_plural = "Promotion Histories"

    def __str__(self):
        return f"{self.staff.full_name} → {self.new_designation}"


class SalaryIncrement(models.Model):
    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="increments",
    )
    year = models.PositiveIntegerField()
    base_salary = models.DecimalField(max_digits=10, decimal_places=2)
    increment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    new_salary = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("staff", "year")
        ordering = ["-year"]
        verbose_name = "Salary Increment"
        verbose_name_plural = "Salary Increments"

    def __str__(self):
        return f"{self.staff.full_name} — {self.year}"