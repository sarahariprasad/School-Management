from django.db import migrations, models
import django.db.models.deletion
import django.core.validators
import staff.models


class Migration(migrations.Migration):
    dependencies = [("staff", "0002_staffprofile_exit_details")]
    operations = [
        migrations.AddField(model_name="staffprofile", name="address", field=models.TextField(blank=True)),
        migrations.AddField(model_name="staffprofile", name="city", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="staffprofile", name="state", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="staffprofile", name="postal_code", field=models.CharField(blank=True, max_length=15)),
        migrations.AddField(model_name="staffprofile", name="address_proof_type", field=models.CharField(blank=True, max_length=60)),
        migrations.AddField(model_name="staffprofile", name="address_proof", field=models.FileField(blank=True, upload_to=staff.models.staff_document_path, validators=[django.core.validators.FileExtensionValidator(["pdf", "jpg", "jpeg", "png"]), staff.models.validate_document_size])),
        migrations.CreateModel(name="EducationRecord", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("qualification", models.CharField(max_length=150)), ("institution", models.CharField(max_length=180)), ("passing_year", models.PositiveSmallIntegerField()), ("certificate", models.FileField(blank=True, upload_to=staff.models.staff_document_path, validators=[django.core.validators.FileExtensionValidator(["pdf", "jpg", "jpeg", "png"]), staff.models.validate_document_size])), ("staff", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="education_records", to="staff.staffprofile"))], options={"ordering": ("-passing_year",)}),
        migrations.CreateModel(name="StaffDocument", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("title", models.CharField(max_length=150)), ("document_type", models.CharField(blank=True, max_length=80)), ("file", models.FileField(upload_to=staff.models.staff_document_path, validators=[django.core.validators.FileExtensionValidator(["pdf", "jpg", "jpeg", "png"]), staff.models.validate_document_size])), ("uploaded_at", models.DateTimeField(auto_now_add=True)), ("staff", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="staff.staffprofile"))], options={"ordering": ("-uploaded_at",)}),
    ]
