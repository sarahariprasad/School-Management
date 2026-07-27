from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="StaffProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("employee_id", models.CharField(max_length=30, unique=True)),
                ("department", models.CharField(choices=[("ACADEMIC", "Academic"), ("ADMINISTRATION", "Administration"), ("FINANCE", "Finance"), ("SUPPORT", "Support")], max_length=20)),
                ("designation", models.CharField(max_length=100)),
                ("joining_date", models.DateField()),
                ("phone", models.CharField(blank=True, max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="staff_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("employee_id",)},
        ),
    ]
