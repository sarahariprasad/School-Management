from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from django.conf import settings
from core.views import dashboard_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard_view, name="dashboard"),
    path("accounts/", include("accounts.urls")),
    path("branches/", include("branches.urls")),
    path("staff/", include("staff.urls")),
    path("students/", include("students.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)