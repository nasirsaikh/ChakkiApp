from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.rbac import MODULE_ROLES, ROLE_ACCOUNTANT, ROLE_MANAGER, ROLE_OPERATOR, ROLE_OWNER, module_required
from .models import ChakkiSettings, PaymentGatewayConfig


@module_required("settings")
def settings_view(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "configuration/settings.html",
        {
            "chakki_settings": ChakkiSettings.load(),
            "payment_gateways": PaymentGatewayConfig.objects.order_by("-is_default", "name"),
        },
    )


@module_required("users")
def users(request: HttpRequest) -> HttpResponse:
    User = get_user_model()
    roles = [ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR, ROLE_ACCOUNTANT]
    groups = {g.name: g for g in Group.objects.filter(name__in=roles)}
    return render(
        request,
        "configuration/users.html",
        {"users": User.objects.order_by("username"), "roles": roles, "groups": groups, "matrix": MODULE_ROLES},
    )


@module_required("users")
@require_POST
def assign_role(request: HttpRequest, pk: int) -> HttpResponse:
    User = get_user_model()
    user = get_object_or_404(User, pk=pk)
    role = request.POST.get("role", "")
    allowed = {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR, ROLE_ACCOUNTANT}
    if role not in allowed:
        messages.error(request, "Unknown role.")
        return redirect("configuration:users")
    role_groups = Group.objects.filter(name__in=allowed)
    user.groups.remove(*role_groups)
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    messages.success(request, f"{user.username} assigned to {role}.")
    return redirect("configuration:users")
