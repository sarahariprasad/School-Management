from datetime import timedelta

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from staff.models import StaffProfile
from students.models import Student, StudentTherapy
from .models import (
    AttendanceStatus, GroupSession, SlotAssignment, StaffAttendance,
    StudentAttendance, TherapistSlot, TherapySession, TimeSlot,
)

S = TherapySession.Status


# ------------------------------------------------- recurring slot handling
def close_inactive_assignments():
    """Recurring slots stop automatically when the student becomes inactive."""
    today = timezone.localdate()
    qs = SlotAssignment.objects.filter(student__is_active=False).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).select_related("student")
    for a in qs:
        last_day = (a.student.inactive_date or today) - timedelta(days=1)
        a.end_date = max(last_day, a.start_date)
        a.save()
        a.sessions.filter(date__gt=a.end_date, status=S.SCHEDULED).delete()


def ensure_sessions(day, closed=False):
    """Create the day's TherapySession rows from the recurring assignments."""
    if not closed:
        close_inactive_assignments()
    due = [
        a for a in SlotAssignment.objects.filter(start_date__lte=day)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=day))
        .select_related("student", "therapy", "staff", "time_slot")
        if day.weekday() in a.weekday_list
        and a.student.is_active
        and day >= a.student.admission_date
    ]
    if not due:
        return
    day_sessions = TherapySession.objects.filter(date=day)
    have_assignment = set(day_sessions.values_list("assignment_id", flat=True))
    have_pair = set(
        day_sessions.filter(status__in=TherapySession.STUDENT_BUSY).values_list("student_id", "therapy_id")
    )
    off_staff = set(
        StaffAttendance.objects.filter(date=day).exclude(status=AttendanceStatus.PRESENT)
        .values_list("staff_id", flat=True)
    )
    off_students = set(
        StudentAttendance.objects.filter(date=day).exclude(status=AttendanceStatus.PRESENT)
        .values_list("student_id", flat=True)
    )
    for a in due:
        if a.id in have_assignment or (a.student_id, a.therapy_id) in have_pair:
            continue
        status, reason, auto = S.SCHEDULED, "", False
        if a.staff_id in off_staff:
            status, reason, auto = S.STAFF_ABSENT, "Auto: therapist absent / on leave", True
        elif a.student_id in off_students:
            status, reason, auto = S.STUDENT_ABSENT, "Auto: student absent / on leave", True
        try:
            with transaction.atomic():
                TherapySession.objects.create(
                    student=a.student, therapy=a.therapy, staff=a.staff, date=day,
                    time_slot=a.time_slot, assignment=a, status=status,
                    absence_reason=reason, auto_marked=auto,
                )
        except IntegrityError:
            pass  # slot taken by a one-off session


def ensure_range(start, end, cap=92):
    close_inactive_assignments()
    day, n = start, 0
    while day <= end and n < cap:
        ensure_sessions(day, closed=True)
        day += timedelta(days=1)
        n += 1


@transaction.atomic
def change_assignment(old, staff, time_slot, effective, weekdays=None):
    """Move a student to a new therapist/slot from `effective` onwards.
    History is kept: the old assignment ends the day before."""
    weekdays = weekdays or old.weekdays
    if effective <= old.start_date:
        old.staff, old.time_slot, old.weekdays = staff, time_slot, weekdays
        old.full_clean()
        old.save()
        old.sessions.filter(date__gte=effective, status=S.SCHEDULED).delete()
        # keep already-marked sessions as records, but detach them so the
        # new slot can generate its own session for those days
        old.sessions.filter(date__gte=effective).update(assignment=None)
        return old
    old.end_date = effective - timedelta(days=1)
    old.save()
    new = SlotAssignment(
        student=old.student, therapy=old.therapy, staff=staff, time_slot=time_slot,
        weekdays=weekdays, start_date=effective, notes=old.notes,
    )
    new.full_clean()
    new.save()
    old.sessions.filter(date__gte=effective, status=S.SCHEDULED).delete()
    return new


@transaction.atomic
def end_assignment(assignment, effective):
    """Stop the recurring slot from `effective` onwards (that day is not held)."""
    last_day = max(effective - timedelta(days=1), assignment.start_date - timedelta(days=1))
    assignment.end_date = last_day
    assignment.save()
    assignment.sessions.filter(date__gte=effective, status=S.SCHEDULED).delete()


def ensure_enrolled(assignment):
    """Assigning a slot implies the student takes that therapy."""
    if not StudentTherapy.objects.filter(
        student_id=assignment.student_id, therapy_id=assignment.therapy_id, is_active=True
    ).exists():
        StudentTherapy.objects.create(
            student_id=assignment.student_id, therapy_id=assignment.therapy_id,
            staff_id=assignment.staff_id,
        )


def unassigned_enrollments(branch_id=None):
    today = timezone.localdate()
    assigned = set(
        SlotAssignment.objects.filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        .values_list("student_id", "therapy_id")
    )
    return [
        e for e in (
            StudentTherapy.objects.filter(is_active=True, student__is_active=True)
            .filter(**({"student__student_branch_id": branch_id} if branch_id else {}))
            .select_related("student", "therapy", "staff__user").order_by("student__name")
        )
        if (e.student_id, e.therapy_id) not in assigned
    ]


# ------------------------------------------------------------- branches
def staff_branch_lookup():
    """ORM path from StaffProfile to its Branch. Auto-detected: StaffProfile.branch,
    else User.branch (via StaffProfile.user). Override in settings.py with
    SCHEDULING_STAFF_BRANCH_LOOKUP = "user__branch"  (or "branch", ...)."""
    custom = getattr(settings, "SCHEDULING_STAFF_BRANCH_LOOKUP", None)
    if custom:
        return custom
    try:
        StaffProfile._meta.get_field("branch")
        return "branch"
    except FieldDoesNotExist:
        pass
    try:
        StaffProfile._meta.get_field("user").related_model._meta.get_field("branch")
        return "user__branch"
    except FieldDoesNotExist:
        return None


def staff_branch_id(staff):
    lookup = staff_branch_lookup()
    if not lookup:
        return None
    obj = staff
    parts = lookup.split("__")
    for part in parts[:-1]:
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return getattr(obj, parts[-1] + "_id", None)


def user_branch_id(user):
    """Branch of the logged-in user (admin's branch or the therapist's own branch)."""
    bid = getattr(user, "branch_id", None)
    if bid:
        return bid
    sp = getattr(user, "staff_profile", None)
    return staff_branch_id(sp) if sp is not None else None


def branch_staff(qs, branch_id):
    """Filter a StaffProfile queryset by branch (no-op if unknown)."""
    lookup = staff_branch_lookup()
    if branch_id and lookup:
        qs = qs.filter(**{lookup: branch_id})
    return qs


def therapist_options(branch_id=None):
    """Therapists for the Change-slot popup, each tagged with .branch_pk."""
    out = list(_therapists(None, branch_id))
    for st in out:
        st.branch_pk = staff_branch_id(st)
    return out


# ------------------------------------------------------- schedule views
def _therapists(therapy=None, branch_id=None, staff_id=None):
    qs = StaffProfile.objects.filter(is_active=True, therapy__isnull=False).select_related("user", "therapy")
    if therapy:
        qs = qs.filter(therapy=therapy)
    qs = branch_staff(qs, branch_id)
    if staff_id:
        qs = qs.filter(pk=staff_id)
    return qs.order_by("employee_id")


def working_slot_map():
    """{staff_id: {slot ids}} only for therapists whose slots are configured."""
    data = {}
    for staff_id, slot_id in TherapistSlot.objects.values_list("staff_id", "time_slot_id"):
        data.setdefault(staff_id, set()).add(slot_id)
    return data


def staff_slot_map():
    return {str(k): sorted(v) for k, v in working_slot_map().items()}


def therapist_cards(day, therapy=None, branch_id=None, staff_id=None):
    """One card per therapist showing only THEIR working slots (5, 8, ...),
    every student in each slot, and how many of those slots are completed."""
    all_slots = list(TimeSlot.objects.all())
    active_ids = {sl.id for sl in all_slots if sl.is_active}
    staff_list = list(_therapists(therapy, branch_id, staff_id))
    work = working_slot_map()
    off = set(
        StaffAttendance.objects.filter(date=day).exclude(status=AttendanceStatus.PRESENT)
        .values_list("staff_id", flat=True)
    )
    sessions = (
        TherapySession.objects.filter(date=day).exclude(status=S.CANCELLED)
        .select_related("student", "therapy", "assignment").order_by("student__name")
    )
    by_key, used = {}, {}
    for s in sessions:
        by_key.setdefault((s.staff_id, s.time_slot_id), []).append(s)
        used.setdefault(s.staff_id, set()).add(s.time_slot_id)

    cards = []
    for st in staff_list:
        configured = work.get(st.id)
        base_ids = (set(configured) & active_ids) if configured else set(active_ids)
        shown = base_ids | used.get(st.id, set())     # never hide a booked session
        rows, slot_map = [], {}
        for sl in all_slots:
            if sl.id not in shown:
                continue
            sess = by_key.get((st.id, sl.id), [])
            pending = sum(1 for x in sess if x.status == S.SCHEDULED)
            missed = sum(1 for x in sess if x.status == S.STAFF_ABSENT)
            if not sess:
                state = "off" if st.id in off else "free"
            elif pending:
                state = "pending"
            elif missed:
                state = "missed"
            else:
                state = "done"
            row = {"slot": sl, "sessions": sess, "state": state, "pending": pending,
                   "extra": sl.id not in base_ids}
            rows.append(row)
            slot_map[sl.id] = row
        booked = [r for r in rows if r["sessions"]]
        done = sum(r["state"] == "done" for r in rows)
        pend = sum(r["state"] == "pending" for r in rows)
        miss = sum(r["state"] == "missed" for r in rows)
        cards.append({
            "staff": st, "rows": rows, "slot_map": slot_map, "off": st.id in off,
            "working": len(base_ids), "configured": bool(configured),
            "booked": len(booked), "done": done, "pending": pend, "missed": miss,
            "empty": sum(r["state"] in ("free", "off") for r in rows),
            "students": sum(len(r["sessions"]) for r in rows),
            "percent": int(100 * done / len(booked)) if booked else 0,
            "all_done": bool(booked) and pend == 0 and miss == 0,
        })
    return [sl for sl in all_slots if sl.is_active], cards


def free_slots(day, therapy=None, branch_id=None, staff_id=None):
    """Per slot: therapists who are present (with their current load) and
    students who have no session in that slot."""
    slots, cards = therapist_cards(day, therapy, branch_id, staff_id)
    absent_students = set(
        StudentAttendance.objects.filter(date=day).exclude(status=AttendanceStatus.PRESENT)
        .values_list("student_id", flat=True)
    )
    students = Student.objects.filter(is_active=True).order_by("name")
    if branch_id:
        students = students.filter(student_branch_id=branch_id)
    students = list(students)
    groups = list(GroupSession.objects.filter(date=day).exclude(status=GroupSession.Status.CANCELLED))
    busy = {}
    for sid, slot_id in TherapySession.objects.filter(
        date=day, status__in=TherapySession.STUDENT_BUSY
    ).values_list("student_id", "time_slot_id"):
        busy.setdefault(slot_id, set()).add(sid)

    out = []
    for i, slot in enumerate(slots):
        free_staff = [
            {"staff": c["staff"], "count": len(c["slot_map"][slot.id]["sessions"])}
            for c in cards
            if not c["off"] and slot.id in c["slot_map"] and not c["slot_map"][slot.id]["extra"]
        ]
        in_group = {
            g.group_id for g in groups
            if g.start_time < slot.end_time and g.end_time > slot.start_time
        }
        free_students = [
            s for s in students
            if s.id not in absent_students and s.id not in busy.get(slot.id, set())
            and s.group_id not in in_group
        ]
        out.append({"slot": slot, "free_staff": free_staff, "free_students": free_students})
    return out


def sync_sessions_with_attendance(kind, person_id, day, status):
    """Absent/leave -> auto-mark that person's scheduled sessions; present -> undo."""
    if kind == "staff":
        qs = TherapySession.objects.filter(staff_id=person_id, date=day)
        absent_status = S.STAFF_ABSENT
    else:
        qs = TherapySession.objects.filter(student_id=person_id, date=day)
        absent_status = S.STUDENT_ABSENT

    if status != AttendanceStatus.PRESENT:
        qs.filter(status=S.SCHEDULED).update(
            status=absent_status, auto_marked=True,
            absence_reason=f"Auto: marked {status} in daily attendance",
        )
    else:
        for sess in qs.filter(status=absent_status, auto_marked=True):
            sess.status, sess.auto_marked, sess.absence_reason = S.SCHEDULED, False, ""
            try:
                with transaction.atomic():
                    sess.save()
            except IntegrityError:
                pass


def student_busy_map():
    """{student_id: [[assignment_id, slot_id, "0,1,2"], ...]} for current recurring slots.
    The Change-slot popup uses it to disable times the student already has
    with another therapy."""
    today = timezone.localdate()
    qs = SlotAssignment.objects.filter(student__is_active=True).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    )
    data = {}
    for aid, student_id, slot_id, days in qs.values_list("id", "student_id", "time_slot_id", "weekdays"):
        data.setdefault(str(student_id), []).append([aid, slot_id, days])
    return data


def complete_sessions(staff_id, day, slot_id=None):
    """Mark every still-scheduled session of a therapist (optionally one slot) completed."""
    qs = TherapySession.objects.filter(staff_id=staff_id, date=day, status=S.SCHEDULED)
    if slot_id:
        qs = qs.filter(time_slot_id=slot_id)
    n = 0
    for sess in qs:
        sess.status = S.COMPLETED
        sess.save()
        n += 1
    return n


def completion_rows(start, end, cap=31, branch_id=None, staff_id=None):
    """Per therapist per day: working/booked/done/pending/missed/empty slots (for Excel)."""
    rows, day, n = [], start, 0
    while day <= end and n < cap:
        _, cards = therapist_cards(day, None, branch_id, staff_id)
        for c in cards:
            if not c["booked"]:
                continue
            rows.append([
                day, c["staff"].full_name, str(c["staff"].therapy), c["working"], c["booked"],
                c["done"], c["pending"], c["missed"], c["empty"],
                "Yes" if c["all_done"] else "No",
            ])
        day += timedelta(days=1)
        n += 1
    return rows


# --------------------------------------------------------------- calendar
def is_working_day(day):
    return day.weekday() in getattr(settings, "SCHEDULING_WORKING_WEEKDAYS", [0, 1, 2, 3, 4])


def _calendar_cell(card, slot, working_day, day):
    """booked | free | na (not available) for one therapist, one slot, one day."""
    base = {"date": day, "staff": card["staff"] if card else None}
    row = card["slot_map"].get(slot.id) if card else None
    if row is None:
        return {**base, "state": "na", "note": "Not working this hour"}
    if row["sessions"]:
        names = [x.student.name for x in row["sessions"]]
        return {**base, "state": "booked", "count": len(names), "names": names,
                "pending": row["pending"], "row_state": row["state"]}
    if card["off"]:
        return {**base, "state": "na", "note": "Absent / on leave"}
    if not working_day:
        return {**base, "state": "na", "note": "Non-working day"}
    return {**base, "state": "free"}


def calendar_day(day, therapy=None, branch_id=None, staff_id=None):
    """Matrix for one day: slots (rows) x therapists (columns)."""
    slots, cards = therapist_cards(day, therapy, branch_id, staff_id)
    wd = is_working_day(day)
    rows, totals = [], {"booked": 0, "free": 0, "na": 0}
    for sl in slots:
        cells = [_calendar_cell(c, sl, wd, day) for c in cards]
        for cell in cells:
            totals[cell["state"]] += 1
        rows.append({"slot": sl, "cells": cells})
    return {"cards": cards, "rows": rows, "totals": totals, "working_day": wd}


def calendar_week(week_start, staff):
    """Matrix for one therapist: slots (rows) x the 7 days of the week."""
    ensure_range(week_start, week_start + timedelta(days=6))
    days = [week_start + timedelta(days=i) for i in range(7)]
    slots, per_day = None, []
    for d in days:
        slots, cards = therapist_cards(d, staff_id=staff.pk)
        per_day.append(cards[0] if cards else None)
    wd = [is_working_day(d) for d in days]
    rows, totals = [], {"booked": 0, "free": 0, "na": 0}
    for sl in slots or []:
        cells = [_calendar_cell(per_day[i], sl, wd[i], days[i]) for i in range(7)]
        for cell in cells:
            totals[cell["state"]] += 1
        rows.append({"slot": sl, "cells": cells})
    return {"days": days, "rows": rows, "totals": totals, "working": wd}
