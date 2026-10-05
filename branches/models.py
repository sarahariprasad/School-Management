from django.db import models
from django.urls import reverse


class Branch(models.Model):
    code = models.CharField(max_length=12, unique=True, db_index=True, help_text="Unique branch code (e.g., BR001)")
    name = models.CharField(max_length=120, db_index=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Branch"
        verbose_name_plural = "Branches"
        indexes = [
            models.Index(fields=["is_active", "name"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def get_absolute_url(self):
        return reverse("branch_edit", kwargs={"pk": self.pk})