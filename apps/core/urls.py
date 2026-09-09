from django.urls import path
from . import views
app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/kpis/", views.dashboard_kpis, name="dashboard_kpis"),
]
