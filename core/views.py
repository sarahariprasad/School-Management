from django.shortcuts import render
from django.db.models import Count, Prefetch
from django.db.models.functions import TruncMonth
from django.utils import timezone
import calendar

from branches.models import Branch
from staff.models import StaffProfile
from students.models import Group, GroupStaffAssignment, Student


def dashboard_view(request):
    context = {}
    
    if request.user.is_authenticated:
        # ── Basic totals ──
        context["total_branches"] = Branch.objects.count()
        context["total_staff"] = StaffProfile.objects.count()
        context["active_staff"] = StaffProfile.objects.filter(is_active=True).count()
        context["total_students"] = Student.objects.count()
        context["active_students"] = Student.objects.filter(is_active=True).count()  # adjust field if different
        context["user_role"] = getattr(request.user, "get_role_display", lambda: "—")()
        context["user_branch"] = getattr(request.user, "branch", None)
        context["today"] = timezone.now()
        
        # ── Year filter for charts ──
        current_year = int(request.GET.get("year", timezone.now().year))
        context["current_year"] = current_year
        context["available_years"] = list(range(current_year - 2, current_year + 1))
        
        # ── Staff Joining Trend (by month) ──
        staff_monthly = (
            StaffProfile.objects.filter(joining_date__year=current_year)
            .annotate(month=TruncMonth("joining_date"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
        staff_counts = [0] * 12
        for entry in staff_monthly:
            staff_counts[entry["month"].month - 1] = entry["count"]
        context["staff_months"] = [calendar.month_abbr[m] for m in range(1, 13)]
        context["staff_counts"] = staff_counts
        
        # ── Student Admission Trend (by month) ──
        # IMPORTANT: Change "admission_date" below if your Student model uses a different field
        # e.g. "joining_date", "created_at", "enrollment_date", etc.
        student_monthly = (
            Student.objects.filter(admission_date__year=current_year)
            .annotate(month=TruncMonth("admission_date"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
        student_counts = [0] * 12
        for entry in student_monthly:
            student_counts[entry["month"].month - 1] = entry["count"]
        context["student_months"] = [calendar.month_abbr[m] for m in range(1, 13)]
        context["student_counts"] = student_counts

        # Dynamic daily roster: every group created in Student Groups appears
        # automatically. Only active students and active staff assignments
        # are shown inside each group.
        
        groups = Group.objects.all().order_by("name").prefetch_related(
            Prefetch(
                "students",
                queryset=Student.objects.filter(is_active=True).order_by("name"),
                to_attr="active_students",
            ),
            Prefetch(
                "staff_assignments",
                queryset=GroupStaffAssignment.objects.filter(is_active=True).select_related("staff__user"),
                to_attr="active_staff_assignments",
            ),
        )

        # Group name -> Bootstrap color
        group_colors = {
            "red": "danger",
            "blue": "primary",
            "green": "success",
            "yellow": "warning",
            "orange": "warning",
            "purple": "secondary",
            "black": "dark",
            "white": "light",
        }
        context["group_rosters"] = [
            {
                "name": f"{group.get_name_display()} Group",
                "color": group_colors.get(
                group.name.strip().lower(),
                "primary", ),
                "group": group,
                "students": group.active_students,
                "staff_assignments": group.active_staff_assignments,
            }
            for group in groups
        ]
        
        # ── Optional: Today's collection (remove if not needed) ──
        # context["today_collection"] = ... your fee logic here ...
    
    return render(request, "dashboard/home.html", context)
