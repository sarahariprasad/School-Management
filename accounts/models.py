from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.SYSTEM_ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        SYSTEM_ADMIN = "SYSTEM_ADMIN", "System admin"
        FINANCE_ADMIN = "FINANCE_ADMIN", "Finance admin"
        BRANCH_ADMIN = "BRANCH_ADMIN", "Branch admin"
        STAFF = "STAFF", "Staff"

    username = None
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="primary_users", help_text="Primary branch for this user."
    )
    accessible_branches = models.ManyToManyField(
        "branches.Branch", blank=True, related_name="authorized_users",
        help_text="Branches this user is permitted to access. Leave empty for a system admin."
    )
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.email

    @property
    def is_system_admin(self):
        return self.is_superuser or self.role == self.Role.SYSTEM_ADMIN
