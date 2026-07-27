from django.db import migrations, models


def copy_primary_branch_to_accessible_branches(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.exclude(branch__isnull=True):
        user.accessible_branches.add(user.branch_id)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="user",
            name="accessible_branches",
            field=models.ManyToManyField(blank=True, help_text="Branches this user is permitted to access. Leave empty for a system admin.", related_name="authorized_users", to="branches.branch"),
        ),
        migrations.AlterField(
            model_name="user",
            name="branch",
            field=models.ForeignKey(blank=True, help_text="Primary branch for this user.", null=True, on_delete=models.SET_NULL, related_name="primary_users", to="branches.branch"),
        ),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(choices=[("SYSTEM_ADMIN", "System admin"), ("FINANCE_ADMIN", "Finance admin"), ("BRANCH_ADMIN", "Branch admin"), ("STAFF", "Staff")], default="STAFF", max_length=20),
        ),
        migrations.RunPython(copy_primary_branch_to_accessible_branches, migrations.RunPython.noop),
    ]
