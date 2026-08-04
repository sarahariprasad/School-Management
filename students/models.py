# students/models.py
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from branches.models import Branch  # import your branch model
from staff.models import StaffProfile   # import your staff model

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

class Class(models.Model):
    name = models.CharField(max_length=50)   # e.g. Grade 1
    section = models.CharField(max_length=10, blank=True, null=True)  # e.g. A, B, C

    class Meta:
        unique_together = ("name", "section")   # ✅ ensures Grade 1-A, Grade 1-B are unique

    def __str__(self):
        return f"{self.name} {self.section or ''}".strip()


class Therapy(models.Model):
    """Therapy options like Speech Therapy, Behavior Therapy, etc."""
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Student(models.Model):
    student_id = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=[('Male','Male'),('Female','Female')])

    # Academic details
    student_class = models.ForeignKey(Class, on_delete=models.SET_NULL, null=True, blank=True)
    assigned_teacher = models.ForeignKey(
        StaffProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students_assigned"
    )
    student_branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)
    # Active status
    is_active = models.BooleanField(default=True, help_text="Mark student as active or inactive")
    inactive_date = models.DateField(null=True, blank=True, help_text="Date when student became inactive")
    # Therapy details (many therapies per student)
    therapies = models.ManyToManyField(Therapy, blank=True, related_name="students")
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
        upload_to=student_document_path,
        blank=True,
        null=True,
        validators=student_document_validators
    )
    father_photo = models.FileField(
        upload_to=student_document_path,
        blank=True,
        null=True,
        validators=student_document_validators
    )
    photo = models.FileField(
        upload_to=student_document_path,
        blank=True,
        null=True,
        validators=student_document_validators
    )

    # Medical documents
    medical_documents = models.FileField(
        upload_to=student_document_path,
        blank=True,
        null=True,
        validators=student_document_validators
    )

    # Address
    address = models.TextField()

    admission_date = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"{self.student_id} — {self.name}"
