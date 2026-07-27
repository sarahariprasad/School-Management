from django.contrib.auth.views import LoginView
from django.shortcuts import render

from .forms import EmailAuthenticationForm


class UserLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm


#def dashboard(request):
 #   return render(request, "dashboard/home.html")
