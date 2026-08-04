from django.shortcuts import render
from branches.models import Branch
from staff.models import StaffProfile
from staff.models import StaffProfile
from branches.models import Branch
from students.models import Student
from django.core.paginator import Paginator
from django.db.models import Q
#from students.models import Student   # assuming you have a Student model

def dashboard_view(request):
    context = {}
    if request.user.is_authenticated:
        context["total_branches"] = Branch.objects.count()
        context["total_staff"] = StaffProfile.objects.count()
        context["total_students"] = Student.objects.count()
        context["user_role"] = getattr(request.user, "get_role_display", None)
        context["user_branch"] = getattr(request.user, "branch", None)
    return render(request, "dashboard/home.html", context)





