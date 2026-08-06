from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from core.permissions import branch_scope, role_required
from .forms import EducationRecordForm, ExperienceFormSet, StaffCreateForm, StaffDocumentForm, StaffExitForm, StaffProfileForm,StaffSelfEditForm,PromotionHistoryForm,ExperienceHistoryForm,SalaryIncrementForm,EducationFormSet,DocumentFormSet,SalaryFormSet,PromotionFormSet
from .models import EducationRecord, StaffDocument, StaffProfile
from django.db.models import Q, Value
from django.db.models.functions import Concat

## staff list view with search ##
@login_required
def staff_list(request):
    search = request.GET.get("search", "").strip()

    staff = branch_scope(
        request.user,
        StaffProfile.objects.select_related("user", "user__branch"),
        "user__branch"
    ).annotate(
        full_name=Concat(
            "user__first_name",
            Value(" "),
            "user__last_name"
        )
    )

    if search:
        staff = staff.filter(
            Q(employee_id__icontains=search) |
            Q(full_name__icontains=search) |
            Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search) |
            Q(user__email__icontains=search) |
            Q(phone__icontains=search) |
            Q(designation__icontains=search) |
            Q(department__icontains=search) |
            Q(city__icontains=search) |
            Q(state__icontains=search)
        )

    return render(request, "staff/list.html", {
        "staff": staff,
        "search": search,
    })

### staff list view with search
@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def staff_create(request):
    if request.method == "POST":
        form = StaffCreateForm(request.POST, request.FILES, actor=request.user)
        education_formset = EducationFormSet(request.POST, request.FILES)
        document_formset = DocumentFormSet(request.POST, request.FILES)
        salary_formset = SalaryFormSet(request.POST)

        if form.is_valid() and education_formset.is_valid() and document_formset.is_valid() and salary_formset.is_valid():
            profile = form.save()
            education_formset.instance = profile
            document_formset.instance = profile
            salary_formset.instance = profile
            education_formset.save()
            document_formset.save()
            salary_formset.save()
            return redirect("staff_list")
    else:
        form = StaffCreateForm(actor=request.user)
        education_formset = EducationFormSet()
        document_formset = DocumentFormSet()
        salary_formset = SalaryFormSet()

    return render(request, "staff/staff_create_tabs.html", {
        "profile_form": form,
        "education_formset": education_formset,
        "document_formset": document_formset,
        "salary_formset": salary_formset,
        "title": "Add staff member",
    })

@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def staff_deactivate(request, pk):
    profile = get_object_or_404(
        branch_scope(request.user, StaffProfile.objects.select_related("user"), "user__branch"), pk=pk
    )
    if not profile.is_active:
        return redirect("staff_list")
    form = StaffExitForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        profile = form.save(commit=False)
        profile.is_active = False
        profile.save(update_fields=["leaving_date", "exit_reason", "is_active"])
        profile.user.is_active = False
        profile.user.save(update_fields=["is_active"])
        return redirect("staff_list")
    return render(request, "staff/deactivate.html", {"form": form, "profile": profile})
	
@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def staff_documents(request, pk):
    profile = get_object_or_404(
        branch_scope(request.user, StaffProfile.objects.select_related("user"), "user__branch"), pk=pk
    )
    return render(request, "staff/documents.html", {"profile": profile, "education_form": EducationRecordForm(), "document_form": StaffDocumentForm()})


@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def education_add(request, pk):
    profile = get_object_or_404(
        branch_scope(request.user, StaffProfile.objects.all(), "user__branch"), pk=pk
    )
    form = EducationRecordForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.staff = profile
        record.save()
    return redirect("staff_documents", pk=pk)
	
@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def document_add(request, pk):
    profile = get_object_or_404(
        branch_scope(request.user, StaffProfile.objects.all(), "user__branch"), pk=pk
    )
    form = StaffDocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.staff = profile
        document.save()
    return redirect("staff_documents", pk=pk)
	
@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def staff_file_download(request, pk, kind, document_pk=None):
    profile = get_object_or_404(
        branch_scope(request.user, StaffProfile.objects.all(), "user__branch"), pk=pk
    )
    if kind == "address":
        file_field = profile.address_proof
    elif kind == "education":
        file_field = get_object_or_404(EducationRecord, pk=document_pk, staff=profile).certificate
    else:
        file_field = get_object_or_404(StaffDocument, pk=document_pk, staff=profile).file
    if not file_field:
        return redirect("staff_documents", pk=pk)
    return FileResponse(file_field.open("rb"), as_attachment=True, filename=file_field.name.rsplit("/", 1)[-1])


@login_required
def staff_profile_edit(request):
    profile = get_object_or_404(StaffProfile, user=request.user)
    form = StaffSelfEditForm(request.POST or None, request.FILES or None, instance=profile)

    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("staff_profile")

    return render(request, "staff/self_edit.html", {"form": form})

@login_required
def staff_profile_view(request):
    profile = get_object_or_404(StaffProfile, user=request.user)
    form = StaffSelfEditForm(instance=profile)
    return render(request, "staff/profile.html", {
        "profile": profile,
        "experience_history": profile.experience_history.all(),
        "promotions": profile.promotions.all(),
        "increments": profile.increments.all(),
        "form": form,
        "is_self": True,
    })

@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def experience_add(request, pk):
    profile = get_object_or_404(
        branch_scope(request.user, StaffProfile.objects.all(), "user__branch"), pk=pk
    )
    form = ExperienceHistoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        exp = form.save(commit=False)
        exp.staff = profile
        exp.save()
        return redirect("staff_profile_admin_view", pk=profile.pk)
    return render(request, "staff/experience_form.html", {"form": form, "profile": profile})

@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def promotion_add(request, pk):
    profile = get_object_or_404(
        branch_scope(request.user, StaffProfile.objects.all(), "user__branch"), pk=pk
    )
    form = PromotionHistoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        promo = form.save(commit=False)
        promo.staff = profile
        promo.save()
        return redirect("staff_profile_admin_view", pk=profile.pk)
    return render(request, "staff/promotion_form.html", {"form": form, "profile": profile})

@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def salary_increment_add(request, pk):
    profile = get_object_or_404(
        branch_scope(request.user, StaffProfile.objects.all(), "user__branch"), pk=pk
    )
    form = SalaryIncrementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # SalaryIncrement.unique_together = ("staff", "year"), but "staff" isn't
        # a form field, so Django's automatic unique_together check is skipped.
        # Check it ourselves or this would raise an unhandled IntegrityError.
        year = form.cleaned_data["year"]
        if profile.increments.filter(year=year).exists():
            form.add_error("year", "A salary increment for this year already exists.")
        else:
            inc = form.save(commit=False)
            inc.staff = profile
            # auto-calc new_salary if not provided
            if not inc.new_salary:
                inc.new_salary = inc.base_salary + inc.increment_amount
            inc.save()
            return redirect("staff_profile_admin_view", pk=profile.pk)
    return render(request, "staff/salary_increment_form.html", {"form": form, "profile": profile})

@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def staff_profile_admin_view(request, pk):
    profile = get_object_or_404(
        branch_scope(request.user, StaffProfile.objects.select_related("user"), "user__branch"), pk=pk
    )
    latest_promotion = profile.promotions.order_by("-promotion_date").first()
    latest_salary = profile.increments.order_by("-year").first()

    return render(request, "staff/profile.html", {
        "profile": profile,
        "experience_history": profile.experience_history.all(),
        "promotions": profile.promotions.all(),
        "increments": profile.increments.all(),
        "latest_promotion": latest_promotion,
        "latest_salary": latest_salary,
        "is_self": False,
    })

### staff view and edit ####
@role_required("SYSTEM_ADMIN", "BRANCH_ADMIN")
def staff_edit(request, pk):
    profile = get_object_or_404(StaffProfile, pk=pk)

    if request.method == "POST":
        form = StaffProfileForm(request.POST, request.FILES, instance=profile)
        education_formset = EducationFormSet(request.POST, request.FILES, instance=profile)
        document_formset = DocumentFormSet(request.POST, request.FILES, instance=profile)
        salary_formset = SalaryFormSet(request.POST, instance=profile)
        experience_formset = ExperienceFormSet(request.POST, request.FILES, instance=profile)
        promotion_formset = PromotionFormSet(request.POST, instance=profile)

        if (form.is_valid() and education_formset.is_valid() and
            document_formset.is_valid() and salary_formset.is_valid() and
            experience_formset.is_valid() and promotion_formset.is_valid()):
            
            profile = form.save()
            education_formset.save()
            document_formset.save()
            salary_formset.save()
            experience_formset.save()
            promotion_formset.save()

            return redirect("staff_list")
    else:
        form = StaffProfileForm(instance=profile)
        education_formset = EducationFormSet(instance=profile)
        document_formset = DocumentFormSet(instance=profile)
        salary_formset = SalaryFormSet(instance=profile)
        experience_formset = ExperienceFormSet(instance=profile)
        promotion_formset = PromotionFormSet(instance=profile)

    return render(request, "staff/profile_edit.html", {
        "profile_form": form,
        "education_formset": education_formset,
        "document_formset": document_formset,
        "salary_formset": salary_formset,
        "experience_formset": experience_formset,
        "promotion_formset": promotion_formset,
        "title": f"Edit Staff: {profile.user.first_name} {profile.user.last_name}",
    })