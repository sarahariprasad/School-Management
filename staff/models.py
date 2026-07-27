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


document_validators = [FileExtensionValidator(["pdf", "jpg", "jpeg", "png"]), validate_document_size]


class StaffProfile(models.Model):
    class Department(models.TextChoices):
        ACADEMIC = "ACADEMIC", "Academic"
        ADMINISTRATION = "ADMINISTRATION", "Administration"
        FINANCE = "FINANCE", "Finance"
        SUPPORT = "SUPPORT", "Support"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_profile")
    employee_id = models.CharField(max_length=30, unique=True)
    department = models.CharField(max_length=20, choices=Department.choices)
    designation = models.CharField(max_length=100)
    joining_date = models.DateField()
    leaving_date = models.DateField(null=True, blank=True)
    exit_reason = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=15, blank=True)
    address_proof_type = models.CharField(max_length=60, blank=True)
    address_proof = models.FileField(upload_to=staff_document_path, blank=True, validators=document_validators)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("employee_id",)

    def __str__(self):
        return f"{self.employee_id} — {self.user.get_full_name() or self.user.email}"


class EducationRecord(models.Model):
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="education_records")
    qualification = models.CharField(max_length=150)
    institution = models.CharField(max_length=180)
    passing_year = models.PositiveSmallIntegerField()
    certificate = models.FileField(upload_to=staff_document_path, blank=True, validators=document_validators)

    class Meta:
        ordering = ("-passing_year",)


class StaffDocument(models.Model):
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=150)
    document_type = models.CharField(max_length=80, blank=True)
    file = models.FileField(upload_to=staff_document_path, validators=document_validators)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-uploaded_at",)

class ExperienceHistory(models.Model):
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="experience_history")
    organization = models.CharField(max_length=200)
    role = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.staff.user.get_full_name()} - {self.role} ({self.organization})"


class PromotionHistory(models.Model):
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="promotions")
    old_designation = models.CharField(max_length=100)
    new_designation = models.CharField(max_length=100)
    promotion_date = models.DateField()

    def __str__(self):
        return f"{self.staff.user.get_full_name()} promoted to {self.new_designation}"


class SalaryIncrement(models.Model):
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="increments")
    year = models.PositiveIntegerField()
    base_salary = models.DecimalField(max_digits=10, decimal_places=2)
    increment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    new_salary = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("staff", "year")
        ordering = ["-year"]

    def __str__(self):
        return f"{self.staff.user.get_full_name()} - {self.year}"

