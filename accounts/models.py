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
        extra_fields.setdefault("is_active", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Custom user model with email-based authentication and role-based access.

    Roles (highest to lowest privilege):
        SYSTEM_ADMIN   → Full access to all branches and all features.
        FINANCE_ADMIN  → Access to fee payment, reports, and financial data across assigned branches.
        BRANCH_ADMIN   → Manage students, staff, and day-to-day operations within assigned branches.
        STAFF          → View-only or limited write access within assigned branches.
    """

    class Role(models.TextChoices):
        SYSTEM_ADMIN = "SYSTEM_ADMIN", "System Admin"
        FINANCE_ADMIN = "FINANCE_ADMIN", "Finance Admin"
        BRANCH_ADMIN = "BRANCH_ADMIN", "Branch Admin"
        STAFF = "STAFF", "Staff"

    username = None
    email = models.EmailField(unique=True, db_index=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STAFF,
        db_index=True,
        help_text="Determines the user's permissions across the system."
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_users",
        help_text="Primary / home branch for this user."
    )
    accessible_branches = models.ManyToManyField(
        "branches.Branch",
        blank=True,
        related_name="authorized_users",
        help_text="Additional branches this user can access. For System Admin, leave empty (all branches are accessible)."
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        ordering = ("email",)
        verbose_name = "User"
        verbose_name_plural = "Users"
        indexes = [
            models.Index(fields=["role", "is_active"]),
            models.Index(fields=["branch", "is_active"]),
        ]

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    @property
    def is_system_admin(self):
        """True if superuser or explicitly assigned SYSTEM_ADMIN role."""
        return self.is_superuser or self.role == self.Role.SYSTEM_ADMIN

    @property
    def is_finance_admin(self):
        return self.role == self.Role.FINANCE_ADMIN

    @property
    def is_branch_admin(self):
        return self.role == self.Role.BRANCH_ADMIN

    @property
    def is_staff_user(self):
        return self.role == self.Role.STAFF

    def get_managed_branch_ids(self):
        """
        Return a list of branch IDs this user is allowed to access.
        System admins get all active branch IDs.
        Others get primary branch + accessible_branches.
        """
        if self.is_system_admin:
            from branches.models import Branch
            return list(Branch.objects.filter(is_active=True).values_list("id", flat=True))

        ids = set()
        if self.branch_id:
            ids.add(self.branch_id)
        ids.update(self.accessible_branches.values_list("id", flat=True))
        return list(ids)

    def has_branch_access(self, branch_id):
        """Check if user can access a specific branch."""
        if self.is_system_admin:
            return True
        if self.branch_id and self.branch_id == branch_id:
            return True
        return self.accessible_branches.filter(id=branch_id).exists()