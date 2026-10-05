# students/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.student_list, name="student_list"),
    path("export/", views.student_export_excel, name="student_export"),
    path("create/", views.student_create, name="student_create"),
    path("bulk-group-reassign/", views.bulk_group_reassign, name="bulk_group_reassign"),

    path("<int:pk>/", views.student_detail, name="student_detail"),
    path("<int:pk>/edit/", views.student_edit, name="student_edit"),
    path("<int:pk>/export/", views.student_export_single_excel, name="student_export_single"),

    path("<int:pk>/remark/add/", views.add_remark, name="add_remark"),
    path("<int:pk>/remarks/export/", views.export_remarks, name="export_remarks"),

    path("<int:pk>/status/", views.toggle_status, name="toggle_status"),
    path("<int:pk>/group/", views.change_group, name="change_group"),

    path("<int:pk>/therapy/add/", views.add_therapy_enrollment, name="add_therapy_enrollment"),
    path(
        "<int:pk>/therapy/<int:enrollment_pk>/edit/",
        views.edit_therapy_enrollment,
        name="edit_therapy_enrollment",
    ),
    path(
        "<int:pk>/therapy/<int:enrollment_pk>/remove/",
        views.remove_therapy_enrollment,
        name="remove_therapy_enrollment",
    ),

    # Groups (Red/Green/Orange) - list + detail, and staff assignment
    path("groups/", views.group_list, name="group_list"),
    path("groups/<int:pk>/", views.group_detail, name="group_detail"),
    path("groups/<int:group_pk>/staff/assign/", views.assign_group_staff, name="assign_group_staff"),
]
