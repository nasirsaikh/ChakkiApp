from __future__ import annotations
from functools import wraps
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

ROLE_OWNER = "Owner"
ROLE_MANAGER = "Manager"
ROLE_OPERATOR = "Operator"
ROLE_ACCOUNTANT = "Accountant"

MODULE_ROLES = {
    "dashboard": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR, ROLE_ACCOUNTANT},
    "customers": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR, ROLE_ACCOUNTANT},
    "grinding": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR},
    "rate_card": {ROLE_OWNER, ROLE_MANAGER},
    "udhaar": {ROLE_OWNER, ROLE_MANAGER, ROLE_ACCOUNTANT},
    "old_udhaar": {ROLE_OWNER, ROLE_MANAGER, ROLE_ACCOUNTANT},
    "accounts": {ROLE_OWNER, ROLE_MANAGER, ROLE_ACCOUNTANT},
    "inventory": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR, ROLE_ACCOUNTANT},
    "purchases": {ROLE_OWNER, ROLE_MANAGER, ROLE_ACCOUNTANT},
    "sales": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR, ROLE_ACCOUNTANT},
    "buyback": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR, ROLE_ACCOUNTANT},
    "production": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR},
    "wastage": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR},
    "utilities": {ROLE_OWNER, ROLE_MANAGER, ROLE_ACCOUNTANT},
    "employees": {ROLE_OWNER, ROLE_MANAGER},
    "attendance": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR},
    "payroll": {ROLE_OWNER, ROLE_MANAGER, ROLE_ACCOUNTANT},
    "maintenance": {ROLE_OWNER, ROLE_MANAGER, ROLE_OPERATOR},
    "suppliers": {ROLE_OWNER, ROLE_MANAGER, ROLE_ACCOUNTANT},
    "reports": {ROLE_OWNER, ROLE_MANAGER, ROLE_ACCOUNTANT},
    "settings": {ROLE_OWNER},
    "users": {ROLE_OWNER},
}

def user_can_access(user, module: str) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    roles = set(user.groups.values_list("name", flat=True))
    return bool(roles & MODULE_ROLES.get(module, set()))

def module_required(module: str):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user_can_access(request.user, module):
                raise PermissionDenied(f"Your role cannot access the {module} module.")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
