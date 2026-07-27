from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from core.permissions import role_required
from .forms import BranchForm
from .models import Branch


@login_required
def branch_list(request):
    if request.user.is_system_admin:
        branches = Branch.objects.all()
    else:
        allowed_ids = list(request.user.accessible_branches.values_list("id", flat=True))
        if request.user.branch_id:
            allowed_ids.append(request.user.branch_id)
        branches = Branch.objects.filter(pk__in=allowed_ids).distinct()
    return render(request, "branches/list.html", {"branches": branches})


@role_required("SYSTEM_ADMIN")
def branch_create(request):
    form = BranchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("branch_list")
    return render(request, "branches/form.html", {"form": form, "title": "Add branch"})


@role_required("SYSTEM_ADMIN")
def branch_edit(request, pk):
    form = BranchForm(request.POST or None, instance=get_object_or_404(Branch, pk=pk))
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("branch_list")
    return render(request, "branches/form.html", {"form": form, "title": "Edit branch"})
