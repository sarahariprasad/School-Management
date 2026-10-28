from django.urls import path
from . import views

app_name = "scheduling"

urlpatterns = [
    path("", views.daily_schedule, name="daily_schedule"),

    # one-off / make-up sessions
    path("sessions/new/", views.session_form, name="session_create"),
    path("sessions/<int:pk>/edit/", views.session_form, name="session_edit"),
    path("sessions/<int:pk>/mark/", views.session_mark, name="session_mark"),
    path("free-slots/", views.free_slots, name="free_slots"),
    path("calendar/", views.calendar_view, name="calendar"),

    # therapist working slots + bulk completion
    path("therapist-slots/", views.therapist_slots, name="therapist_slots"),
    path("complete/", views.slot_complete, name="slot_complete"),

    # recurring slot assignments
    path("assignments/", views.assignment_list, name="assignment_list"),
    path("assignments/new/", views.assignment_create, name="assignment_create"),
    path("assignments/<int:pk>/change/", views.assignment_change, name="assignment_change"),
    path("assignments/<int:pk>/end/", views.assignment_end, name="assignment_end"),

    # attendance + reports
    path("attendance/<str:kind>/", views.attendance_mark, name="attendance"),
    path("students/<int:pk>/report/", views.student_report, name="student_report"),
    path("staff/<int:pk>/report/", views.staff_report, name="staff_report"),

    # group hours
    path("groups/", views.group_session_list, name="group_list"),
    path("groups/new/", views.group_session_form, name="group_create"),
    path("groups/<int:pk>/edit/", views.group_session_form, name="group_edit"),
    path("groups/<int:pk>/attendance/", views.group_attendance, name="group_attendance"),

    # Excel exports
    path("export/schedule/", views.export_schedule, name="export_schedule"),
    path("export/attendance/", views.export_attendance, name="export_attendance"),
]
