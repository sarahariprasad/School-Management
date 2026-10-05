from datetime import date

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from staff.models import StaffProfile
from students.models import Group, GroupStaffAssignment, Student


@override_settings(STORAGES={
    **settings.STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class DashboardGroupRosterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="admin@example.com",
            password="password",
            role=User.Role.SYSTEM_ADMIN,
        )
        self.green = Group.objects.create(name=Group.GREEN)
        self.red = Group.objects.create(name=Group.RED)
        Group.objects.create(name=Group.ORANGE)
        Student.objects.create(
            student_id="GREEN-001", name="Green Student", date_of_birth=date(2018, 1, 1),
            gender="Male", group=self.green, mother_name="Mother", father_name="Father", address="Address",
        )
        staff_user = User.objects.create_user(email="therapist@example.com", password="password")
        staff = StaffProfile.objects.create(
            user=staff_user, employee_id="STAFF-001", department=StaffProfile.Department.ACADEMIC,
            designation="Therapist", joining_date=date.today(),
        )
        GroupStaffAssignment.objects.create(group=self.green, staff=staff)

    def test_dashboard_shows_every_group_roster(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Green Group")
        self.assertContains(response, "Red Group")
        self.assertContains(response, "Orange Group")
        self.assertContains(response, "Green Student")
        self.assertContains(response, "Therapist")
