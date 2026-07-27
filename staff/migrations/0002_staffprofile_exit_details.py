from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("staff", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="staffprofile",
            name="leaving_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="staffprofile",
            name="exit_reason",
            field=models.TextField(blank=True),
        ),
    ]
