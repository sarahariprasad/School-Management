from django.urls import path
from . import views

urlpatterns = [
    path("", views.staff_list, name="staff_list"),
    path("new/", views.staff_create, name="staff_create"),
    path("<int:pk>/edit/", views.staff_edit, name="staff_edit"),
    path("<int:pk>/deactivate/", views.staff_deactivate, name="staff_deactivate"),
    path("<int:pk>/documents/", views.staff_documents, name="staff_documents"),
    path("<int:pk>/documents/education/add/", views.education_add, name="education_add"),
    path("<int:pk>/documents/upload/", views.document_add, name="document_add"),
    path("<int:pk>/documents/download/address/", views.staff_file_download, {"kind": "address"}, name="address_proof_download"),
    path("<int:pk>/documents/download/education/<int:document_pk>/", views.staff_file_download, {"kind": "education"}, name="education_download"),
    path("<int:pk>/documents/download/file/<int:document_pk>/", views.staff_file_download, {"kind": "document"}, name="staff_document_download"),
    path("profile/", views.staff_profile_view, name="staff_profile"),
    path("profile/edit/", views.staff_profile_edit, name="staff_profile_edit"),

    # History management
    path("profile/<int:pk>/experience/add/", views.experience_add, name="experience_add"),
    path("profile/<int:pk>/promotion/add/", views.promotion_add, name="promotion_add"),
    path("profile/<int:pk>/salary/add/", views.salary_increment_add, name="salary_increment_add"),

    # Admin profile view
    path("profile/<int:pk>/", views.staff_profile_admin_view, name="staff_profile_admin_view"),
]

