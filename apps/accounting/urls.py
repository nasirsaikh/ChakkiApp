from django.urls import path
from . import views
app_name = "accounting"
urlpatterns = [
    path("udhaar/", views.udhaar, name="udhaar"),
    path("old-udhaar/", views.old_udhaar, name="old_udhaar"),
    path("accounts/", views.accounts, name="accounts"),
    path("reports/", views.reports, name="reports"),
]
