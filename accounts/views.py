from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy

from .forms import EmailAuthenticationForm


class UserLoginView(LoginView):
    """Custom login view using email authentication."""
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


class UserPasswordChangeView(PasswordChangeView):
    """Allow logged-in users to change their password."""
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("password_change_done")

    def form_valid(self, form):
        messages.success(self.request, "Your password has been changed successfully.")
        return super().form_valid(form)


@login_required
def profile(request):
    """
    If the user has a StaffProfile, redirect to the rich staff profile view.
    Otherwise, show a basic user profile page.
    """
    # Avoid circular import by importing here
    from staff.models import StaffProfile

    if StaffProfile.objects.filter(user=request.user).exists():
        return redirect("staff_profile")  # your staff app's self-profile URL name

    # Fallback for non-staff users (e.g., superusers, parents, students)
    user = request.user
    context = {
        "user": user,
        "managed_branches": user.get_managed_branch_ids(),
    }
    return render(request, "accounts/profile.html", context)