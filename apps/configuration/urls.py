from django.urls import path
from . import views
app_name = "configuration"
urlpatterns = [
    path("", views.settings_view, name="settings"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/role/", views.assign_role, name="assign_role"),
]
