from django.urls import path
from . import views

urlpatterns = [
    path("", views.branch_list, name="branch_list"),
    path("new/", views.branch_create, name="branch_create"),
    path("<int:pk>/edit/", views.branch_edit, name="branch_edit"),
]
