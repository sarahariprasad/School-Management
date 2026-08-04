# students/views.py
from django.shortcuts import render, redirect, get_object_or_404
from .models import Student
from core.permissions import role_required 
from .forms import StudentForm
from django.db.models import Q
from django.core.exceptions import FieldError


def student_list(request):
    query = request.GET.get("q")  # search keyword
    students = Student.objects.select_related("student_class", "assigned_teacher").prefetch_related("therapies")

    try:
        if query:
            students = students.filter(
            Q(name__icontains=query) |
            Q(student_id__icontains=query) |
            Q(student_class__name__icontains=query) |
            Q(assigned_teacher__name__icontains=query)
        )
    except FieldError:
    # gracefully handle wrong field lookups
        students = students.none()
        error_message = "Invalid search field. Please search by name, ID, class, or teacher."

    status = request.GET.get("status")
    if status == "active":
        students = students.filter(is_active=True)
    elif status == "inactive":
        students = students.filter(is_active=False)

    return render(request, "students/student_list.html", {"students": students})

@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def student_create(request):
    if request.method == "POST":
        form = StudentForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect("student_list")
    else:
        form = StudentForm()
    return render(request, "students/student_form.html", {"form": form})

@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == "POST":
        form = StudentForm(request.POST, request.FILES, instance=student)
        if form.is_valid():
            form.save()
            return redirect("student_list")  # ✅ redirect to list instead of detail
    else:
        form = StudentForm(instance=student)
    return render(request, "students/student_edit.html", {"form": form, "student": student})