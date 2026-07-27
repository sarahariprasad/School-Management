from django.contrib import admin
from django.urls import include, path

from core.views import dashboard_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard_view, name="dashboard"),
    path("accounts/", include("accounts.urls")),
    path("branches/", include("branches.urls")),
    path("staff/", include("staff.urls")),
]
