from django.urls import path
from . import views
app_name = "workforce"
urlpatterns = [
    path("employees/", views.employees, name="employees"),
    path("attendance/", views.attendance, name="attendance"),
    path("payroll/", views.payroll, name="payroll"),
    path("payroll/<int:pk>/post/", views.payroll_post, name="payroll_post"),
    path("maintenance/", views.maintenance, name="maintenance"),
]
