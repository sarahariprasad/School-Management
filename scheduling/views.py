from collections import Counter
from datetime import datetime, timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from branches.models import Branch
from staff.models import StaffProfile
from students.models import Student, Therapy
from . import exports, services
from .access import ADMIN_ROLES, has_schedule_access
from .forms import GroupSessionForm, SlotAssignmentForm, TherapySessionForm
from .models import (
    WEEKDAYS, AttendanceStatus, GroupSession, GroupSessionAttendance, SlotAssignment,
    StaffAttendance, StudentAttendance, TherapistSlot, TherapySession, TimeSlot,
)


# ------------------------------------------------------------- helpers


def schedule_access(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not has_schedule_access(user):
            messages.error(request, "Scheduling is available to administrators only.",
                           fail_silently=True)
            try:
                return redirect("staff_profile")
            except NoReverseMatch:
                raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def can_change(user):
    """Who may create/change/end recurring slots (all users with scheduling access).
    SCHEDULE_CHANGE_ADMIN_ONLY = True narrows it to superusers + SYSTEM_ADMIN/BRANCH_ADMIN."""
    if not has_schedule_access(user):
        return False
    if getattr(settings, "SCHEDULE_CHANGE_ADMIN_ONLY", False):
        return user.is_superuser or getattr(user, "role", None) in {"SYSTEM_ADMIN", "BRANCH_ADMIN"}
    return True


def manager_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not can_change(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return schedule_access(wrapper)


def parse_day(request, key="date"):
    raw = request.GET.get(key) or request.POST.get(key)
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return timezone.localdate()


def safe_next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return fallback


def _int(value):
    return int(value) if value and str(value).isdigit() else None


ALL_BRANCH_ROLES = {"SYSTEM_ADMIN", "FINANCE_ADMIN"}


def branch_scope(request):
    """(branch_id, locked). System/Finance admins can pick any branch;
    branch admins and therapists are limited to their own branch."""
    user = request.user
    own = services.user_branch_id(user)
    if user.is_superuser or getattr(user, "role", None) in ALL_BRANCH_ROLES or not own:
        return _int(request.GET.get("branch")), False
    return own, True


def filters_context(request, with_staff=True, with_therapy=True):
    """Branch / therapy / therapist (by name) filters shared by the schedule pages."""
    branch_id, locked = branch_scope(request)
    ctx = {
        "branches": Branch.objects.filter(pk=branch_id) if locked else Branch.objects.all(),
        "branch_sel": branch_id, "branch_locked": locked,
    }
    qs = f"&branch={branch_id}" if branch_id else ""
    therapy = None
    if with_therapy:
        therapy = Therapy.objects.filter(pk=_int(request.GET.get("therapy"))).first()
        ctx.update(therapies=Therapy.objects.all(), therapy=therapy)
        if therapy:
            qs += f"&therapy={therapy.pk}"
    if with_staff:
        choices = list(services._therapists(therapy, branch_id))
        staff_sel = _int(request.GET.get("staff"))
        if staff_sel not in {c.pk for c in choices}:
            staff_sel = None
        ctx.update(staff_choices=choices, staff_sel=staff_sel)
        if staff_sel:
            qs += f"&staff={staff_sel}"
    ctx["filter_qs"] = qs
    return ctx


def _range(request, default_days=30):
    end = parse_day(request, "to")
    start = parse_day(request, "from") if request.GET.get("from") else end - timedelta(days=default_days)
    return start, end


# ------------------------------------------------------------ schedule
@schedule_access
def daily_schedule(request):
    day = parse_day(request)
    f = filters_context(request)
    services.ensure_sessions(day)
    slots, cards = services.therapist_cards(day, f["therapy"], f["branch_sel"], f["staff_sel"])
    sessions = TherapySession.objects.filter(date=day, staff_id__in=[c["staff"].pk for c in cards])
    groups = GroupSession.objects.filter(date=day).select_related("group", "staff__user")
    if f["branch_sel"]:
        groups = groups.filter(group__students__student_branch=f["branch_sel"]).distinct()
    return render(request, "scheduling/daily_schedule.html", {
        **f, "day": day, "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1),
        "cards": cards, "slots": slots,
        "counts": dict(Counter(sessions.values_list("status", flat=True))),
        "total": sessions.count(), "group_sessions": groups,
        "statuses": TherapySession.Status,
        "can_change": can_change(request.user),
        "staff_options": services.therapist_options(f["branch_sel"]),
        "weekdays": WEEKDAYS,
        "busy_map": services.student_busy_map(),
        "staff_slots": services.staff_slot_map(),
    })


@schedule_access
def calendar_view(request):
    """Calendar: every hour shown as Booked / Free / Not available."""
    day = parse_day(request)
    f = filters_context(request)
    mode = request.GET.get("mode") or ("week" if f["staff_sel"] else "day")
    ctx = {**f, "day": day, "mode": mode, "can_change": can_change(request.user)}
    if mode == "week" and f["staff_sel"]:
        staff = next(c for c in f["staff_choices"] if c.pk == f["staff_sel"])
        ws = day - timedelta(days=day.weekday())
        ctx.update(week=services.calendar_week(ws, staff), cal_staff=staff, week_start=ws,
                   prev_day=ws - timedelta(days=7), next_day=ws + timedelta(days=7))
    else:
        services.ensure_sessions(day)
        ctx.update(mode="day", need_staff=(mode == "week"),
                   cal=services.calendar_day(day, f["therapy"], f["branch_sel"], f["staff_sel"]),
                   prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1))
    return render(request, "scheduling/calendar.html", ctx)


@schedule_access
def session_form(request, pk=None):
    """One-off / make-up session (use Assignments for recurring slots)."""
    instance = get_object_or_404(TherapySession, pk=pk) if pk else None
    if request.method == "POST":
        form = TherapySessionForm(request.POST, instance=instance)
        if form.is_valid():
            obj = form.save()
            messages.success(request, "Session saved.")
            return redirect(f"{reverse('scheduling:daily_schedule')}?date={obj.date:%Y-%m-%d}")
    else:
        initial = {}
        if not instance:
            g = request.GET
            if g.get("date"):
                initial["date"] = parse_day(request)
            for key, field in (("slot", "time_slot"), ("student", "student")):
                if g.get(key):
                    initial[field] = g[key]
            if g.get("staff"):
                initial["staff"] = g["staff"]
                st = StaffProfile.objects.filter(pk=_int(g["staff"])).first()
                if st and st.therapy_id:
                    initial["therapy"] = st.therapy_id
            if g.get("reschedule"):
                old = get_object_or_404(TherapySession, pk=g["reschedule"])
                initial.update(student=old.student_id, therapy=old.therapy_id,
                               date=old.date, rescheduled_from=old.pk)
        form = TherapySessionForm(instance=instance, initial=initial)
    return render(request, "scheduling/session_form.html", {"form": form, "instance": instance})


@schedule_access
@require_POST
def session_mark(request, pk):
    session = get_object_or_404(TherapySession, pk=pk)
    status = request.POST.get("status")
    if status not in TherapySession.Status.values:
        raise Http404
    session.status = status
    session.auto_marked = False
    if status in ("student_absent", "staff_absent", "cancelled"):
        session.absence_reason = request.POST.get("reason", session.absence_reason)
    else:
        session.absence_reason = ""
    try:
        session.full_clean()
        session.save()
        messages.success(request, f"Marked as {session.get_status_display()}.")
    except ValidationError as exc:
        messages.error(request, "Could not update: " + " ".join(exc.messages))
    fallback = f"{reverse('scheduling:daily_schedule')}?date={session.date:%Y-%m-%d}"
    return redirect(safe_next(request, fallback))


@schedule_access
def free_slots(request):
    day = parse_day(request)
    f = filters_context(request)
    services.ensure_sessions(day)
    staff_ids = [c.pk for c in f["staff_choices"]]
    absent_staff = StaffAttendance.objects.filter(date=day, staff_id__in=staff_ids).exclude(
        status=AttendanceStatus.PRESENT).select_related("staff__user")
    absent_students = StudentAttendance.objects.filter(date=day).exclude(
        status=AttendanceStatus.PRESENT).select_related("student")
    if f["branch_sel"]:
        absent_students = absent_students.filter(student__student_branch_id=f["branch_sel"])
    return render(request, "scheduling/free_slots.html", {
        **f, "day": day, "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1),
        "rows": services.free_slots(day, f["therapy"], f["branch_sel"], f["staff_sel"]),
        "absent_staff": absent_staff, "absent_students": absent_students,
    })


# ------------------------------------------------ therapist working slots
@manager_required
def therapist_slots(request):
    """Matrix: which of the day's slots each therapist works (e.g. 5 of 8)."""
    slots = list(TimeSlot.objects.filter(is_active=True))
    staff_list = list(StaffProfile.objects.filter(is_active=True, therapy__isnull=False)
                      .select_related("user", "therapy").order_by("employee_id"))
    current = services.working_slot_map()
    today = timezone.localdate()
    if request.method == "POST":
        problems = []
        with transaction.atomic():
            for st in staff_list:
                chosen = {int(x) for x in request.POST.getlist(f"slots_{st.pk}") if x.isdigit()}
                chosen &= {sl.id for sl in slots}
                in_use = set(
                    SlotAssignment.objects.filter(staff=st, student__is_active=True)
                    .filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
                    .values_list("time_slot_id", flat=True)
                )
                if chosen:
                    blocked = in_use - chosen
                    if blocked:
                        names = ", ".join(str(sl) for sl in slots if sl.id in blocked)
                        problems.append(f"{st.full_name} still has students in {names}; "
                                        f"move them first. Those slots were kept.")
                        chosen |= blocked
                TherapistSlot.objects.filter(staff=st).exclude(time_slot_id__in=chosen).delete()
                for sid in chosen - {x.time_slot_id for x in TherapistSlot.objects.filter(staff=st)}:
                    TherapistSlot.objects.create(staff=st, time_slot_id=sid)
        messages.success(request, "Therapist working slots saved.")
        for msg in problems:
            messages.warning(request, msg)
        return redirect("scheduling:therapist_slots")
    rows = [{
        "staff": st, "configured": st.id in current,
        "cells": [{"slot": sl, "on": (st.id not in current) or (sl.id in current[st.id])} for sl in slots],
        "count": len(current[st.id] & {sl.id for sl in slots}) if st.id in current else len(slots),
    } for st in staff_list]
    return render(request, "scheduling/therapist_slots.html", {"slots": slots, "rows": rows})


@schedule_access
@require_POST
def slot_complete(request):
    """Mark all still-scheduled students of a therapist (one slot, or the whole day) completed."""
    staff = get_object_or_404(StaffProfile, pk=_int(request.POST.get("staff")))
    day = parse_day(request)
    n = services.complete_sessions(staff.pk, day, _int(request.POST.get("slot")))
    messages.success(request, f"{n} session{'s' if n != 1 else ''} marked completed for {staff.full_name}.")
    return redirect(safe_next(request, f"{reverse('scheduling:daily_schedule')}?date={day:%Y-%m-%d}"))


# --------------------------------------------------------- assignments
@schedule_access
def assignment_list(request):
    today = timezone.localdate()
    f = filters_context(request, with_staff=False, with_therapy=False)
    branch_id = f["branch_sel"]
    status = request.GET.get("status", "current")
    qs = SlotAssignment.objects.select_related("student__group", "therapy", "staff__user", "time_slot")
    if status == "current":
        qs = qs.filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
    elif status == "ended":
        qs = qs.filter(end_date__lt=today)
    if branch_id:
        qs = qs.filter(student__student_branch_id=branch_id)
    therapy = Therapy.objects.filter(pk=_int(request.GET.get("therapy"))).first()
    if therapy:
        qs = qs.filter(therapy=therapy)
    therapists = services.branch_staff(
        StaffProfile.objects.filter(is_active=True, therapy__isnull=False).select_related("user", "therapy"),
        branch_id)
    staff_id = _int(request.GET.get("staff"))
    if staff_id:
        qs = qs.filter(staff_id=staff_id)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(student__name__icontains=q) | Q(student__student_id__icontains=q))
    if request.GET.get("export") == "xlsx":
        return exports.assignments_workbook(qs, f"slot_assignments_{today}.xlsx")
    return render(request, "scheduling/assignment_list.html", {
        **f, "assignments": qs, "status": status, "q": q, "therapy": therapy, "staff_id": staff_id,
        "therapies": Therapy.objects.all(), "therapists": therapists,
        "unassigned": services.unassigned_enrollments(branch_id),
        "slots": TimeSlot.objects.filter(is_active=True),
        "can_change": can_change(request.user), "today": today,
        "staff_options": services.therapist_options(f["branch_sel"]),
        "weekdays": WEEKDAYS,
        "busy_map": services.student_busy_map(),
        "staff_slots": services.staff_slot_map(),
    })


@manager_required
def assignment_create(request):
    if request.method == "POST":
        form = SlotAssignmentForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                obj = form.save()
                services.ensure_enrolled(obj)
            messages.success(
                request,
                f"{obj.student.name} assigned to {obj.staff.full_name} at {obj.time_slot} "
                f"({obj.weekday_display}). The slot continues until the student is inactive.")
            return redirect("scheduling:assignment_list")
    else:
        g, initial = request.GET, {}
        for key, field in (("student", "student"), ("therapy", "therapy"),
                           ("staff", "staff"), ("slot", "time_slot")):
            if g.get(key):
                initial[field] = g[key]
        if g.get("staff") and not g.get("therapy"):
            st = StaffProfile.objects.filter(pk=_int(g["staff"])).first()
            if st and st.therapy_id:
                initial["therapy"] = st.therapy_id
        form = SlotAssignmentForm(initial=initial)
    return render(request, "scheduling/assignment_form.html", {"form": form})


@manager_required
@require_POST
def assignment_change(request, pk):
    old = get_object_or_404(SlotAssignment, pk=pk)
    staff = StaffProfile.objects.filter(pk=_int(request.POST.get("staff"))).first()
    slot = TimeSlot.objects.filter(pk=_int(request.POST.get("time_slot"))).first()
    days = sorted({d for d in request.POST.getlist("weekdays") if d in "0123456" and d})
    effective = parse_day(request, "effective_from")
    fallback = reverse("scheduling:assignment_list")
    if not staff or not slot:
        messages.error(request, "Choose a therapist and a time slot.")
        return redirect(safe_next(request, fallback))
    try:
        new = services.change_assignment(old, staff, slot, effective, ",".join(days) or None)
        messages.success(
            request,
            f"{new.student.name} moved to {staff.full_name} at {slot} from {effective:%d %b %Y}.")
    except ValidationError as exc:
        messages.error(request, "Could not change: " + " ".join(exc.messages))
    return redirect(safe_next(request, fallback))


@manager_required
@require_POST
def assignment_end(request, pk):
    a = get_object_or_404(SlotAssignment, pk=pk)
    effective = parse_day(request, "effective_from")
    services.end_assignment(a, effective)
    messages.success(request, f"Recurring slot for {a.student.name} ended from {effective:%d %b %Y}.")
    return redirect(safe_next(request, reverse("scheduling:assignment_list")))


# ---------------------------------------------------------- attendance
@schedule_access
def attendance_mark(request, kind):
    if kind not in ("student", "staff"):
        raise Http404
    day = parse_day(request)
    f = filters_context(request, with_staff=False, with_therapy=False)
    if kind == "staff":
        people = services.branch_staff(
            StaffProfile.objects.filter(is_active=True).select_related("user"), f["branch_sel"]
        ).order_by("employee_id")
        model, field = StaffAttendance, "staff"
    else:
        people = Student.objects.filter(is_active=True).order_by("name")
        if f["branch_sel"]:
            people = people.filter(student_branch_id=f["branch_sel"])
        model, field = StudentAttendance, "student"

    if request.method == "POST":
        with transaction.atomic():
            services.ensure_sessions(day)
            for p in people:
                status = request.POST.get(f"status_{p.pk}")
                if status not in AttendanceStatus.values:
                    continue
                model.objects.update_or_create(
                    **{field: p, "date": day},
                    defaults={"status": status,
                              "remarks": request.POST.get(f"remarks_{p.pk}", "").strip()},
                )
                services.sync_sessions_with_attendance(kind, p.pk, day, status)
        messages.success(request, f"{kind.title()} attendance saved for {day:%d %b %Y}.")
        return redirect(f"{reverse('scheduling:attendance', args=[kind])}?date={day:%Y-%m-%d}{f['filter_qs']}")

    existing = {getattr(a, field + "_id"): a for a in model.objects.filter(date=day)}
    return render(request, "scheduling/attendance.html", {
        **f, "kind": kind, "day": day, "choices": AttendanceStatus.choices,
        "rows": [{"person": p, "record": existing.get(p.pk)} for p in people],
        "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1),
    })


@schedule_access
def export_attendance(request):
    start = parse_day(request, "from") if request.GET.get("from") else parse_day(request, "date")
    end = parse_day(request, "to") if request.GET.get("to") else start
    branch_id, _ = branch_scope(request)
    students = StudentAttendance.objects.filter(date__range=(start, end))
    staff = StaffAttendance.objects.filter(date__range=(start, end))
    if branch_id:
        students = students.filter(student__student_branch_id=branch_id)
        staff = staff.filter(staff__in=services.branch_staff(StaffProfile.objects.all(), branch_id))
    return exports.attendance_workbook(students, staff, f"attendance_{start}_{end}.xlsx")


@schedule_access
def export_schedule(request):
    start = parse_day(request, "from") if request.GET.get("from") else parse_day(request, "date")
    end = parse_day(request, "to") if request.GET.get("to") else start
    end = max(start, end)
    branch_id, _ = branch_scope(request)
    staff_id = _int(request.GET.get("staff"))
    services.ensure_range(start, end)
    qs = TherapySession.objects.filter(date__range=(start, end)).exclude(
        status=TherapySession.Status.CANCELLED)
    if branch_id or staff_id:
        ids = services._therapists(None, branch_id, staff_id).values_list("pk", flat=True)
        qs = qs.filter(staff_id__in=list(ids))
    return exports.sessions_workbook(
        qs, f"schedule_{start}_{end}.xlsx",
        completion=services.completion_rows(start, end, branch_id=branch_id, staff_id=staff_id),
    )


# ------------------------------------------------------------- reports
def _report(request, kind, person):
    start, end = _range(request)
    services.ensure_range(start, min(end, timezone.localdate()))
    if kind == "staff":
        sessions = person.scheduled_sessions.filter(date__range=(start, end))
    else:
        sessions = person.therapy_slots.filter(date__range=(start, end))
    sessions = sessions.exclude(status=TherapySession.Status.CANCELLED).select_related(
        "therapy", "staff__user", "student", "time_slot", "assignment")
    attendance = person.attendance_records.filter(date__range=(start, end))
    group_att = (
        person.group_attendance.filter(group_session__date__range=(start, end))
        .select_related("group_session__group") if kind == "student" else []
    )
    if request.GET.get("export") == "xlsx":
        name = person.full_name if kind == "staff" else person.name
        return exports.person_workbook(
            kind, person, sessions, attendance, group_att,
            f"{kind}_{name.replace(' ', '_')}_{start}_{end}.xlsx")
    return render(request, "scheduling/person_report.html", {
        "kind": kind, "person": person, "start": start, "end": end,
        "sessions": sessions, "attendance": attendance, "group_att": group_att,
        "assignments": person.slot_assignments.filter(
            Q(end_date__isnull=True) | Q(end_date__gte=timezone.localdate())
        ).select_related("student", "therapy", "staff__user", "time_slot"),
        "session_counts": dict(Counter(s.get_status_display() for s in sessions)),
        "att_counts": dict(Counter(a.get_status_display() for a in attendance)),
        "can_change": can_change(request.user),
        "slots": TimeSlot.objects.filter(is_active=True),
        "staff_options": services.therapist_options(),
        "weekdays": WEEKDAYS,
        "busy_map": services.student_busy_map(),
        "staff_slots": services.staff_slot_map(),
    })


@schedule_access
def student_report(request, pk):
    return _report(request, "student", get_object_or_404(Student, pk=pk))


@schedule_access
def staff_report(request, pk):
    return _report(request, "staff", get_object_or_404(StaffProfile.objects.select_related("user"), pk=pk))


# ---------------------------------------------------------- group hours
@schedule_access
def group_session_list(request):
    day = parse_day(request)
    return render(request, "scheduling/group_session_list.html", {
        "day": day, "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1),
        "sessions": GroupSession.objects.filter(date=day).select_related("group", "staff__user"),
    })


@schedule_access
def group_session_form(request, pk=None):
    instance = get_object_or_404(GroupSession, pk=pk) if pk else None
    form = GroupSessionForm(request.POST or None, instance=instance,
                            initial={"date": parse_day(request)} if not instance else None)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        for s in Student.objects.filter(group=obj.group, is_active=True):
            GroupSessionAttendance.objects.get_or_create(group_session=obj, student=s)
        messages.success(request, "Group session saved.")
        return redirect(f"{reverse('scheduling:group_list')}?date={obj.date:%Y-%m-%d}")
    return render(request, "scheduling/group_session_form.html", {"form": form, "instance": instance})


@schedule_access
def group_attendance(request, pk):
    gs = get_object_or_404(GroupSession.objects.select_related("group"), pk=pk)
    for s in Student.objects.filter(group=gs.group, is_active=True):
        GroupSessionAttendance.objects.get_or_create(group_session=gs, student=s)
    records = gs.attendance.select_related("student").order_by("student__name")
    if request.method == "POST":
        for r in records:
            status = request.POST.get(f"status_{r.pk}")
            if status in AttendanceStatus.values:
                r.status = status
                r.remarks = request.POST.get(f"remarks_{r.pk}", "").strip()
                r.save()
        messages.success(request, "Group attendance saved.")
        return redirect(f"{reverse('scheduling:group_list')}?date={gs.date:%Y-%m-%d}")
    return render(request, "scheduling/group_attendance.html", {
        "gs": gs, "records": records, "choices": AttendanceStatus.choices})
