# students/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.student_list, name="student_list"),
    path("create/", views.student_create, name="student_create"),
    path("<int:pk>/edit/", views.student_edit, name="student_edit"),
    
]