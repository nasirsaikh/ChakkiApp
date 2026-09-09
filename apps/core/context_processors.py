from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .rbac import user_can_access

NAVIGATION_GROUPS = [
    (
        _("Overview"),
        [
            ("dashboard", _("Dashboard"), "core:dashboard", "layout-dashboard"),
            ("customers", _("Customers"), "customers:list", "users"),
        ],
    ),
    (
        _("Operations"),
        [
            ("grinding", _("Grinding"), "operations:grinding_board", "wheat"),
            ("rate_card", _("Rate Card"), "operations:rate_card", "badge-indian-rupee"),
            ("buyback", _("Buyback"), "operations:buyback", "repeat-2"),
            ("production", _("Production"), "operations:production", "factory"),
            ("wastage", _("Wastage"), "operations:wastage", "trash-2"),
            ("utilities", _("Utilities"), "operations:utilities", "zap"),
        ],
    ),
    (
        _("Accounting"),
        [
            ("udhaar", _("Udhaar"), "accounting:udhaar", "hand-coins"),
            ("old_udhaar", _("Old Udhaar"), "accounting:old_udhaar", "history"),
            ("accounts", _("Accounts"), "accounting:accounts", "landmark"),
            ("reports", _("Reports"), "accounting:reports", "chart-no-axes-combined"),
        ],
    ),
    (
        _("Stock & Trade"),
        [
            ("inventory", _("Inventory"), "inventory:stock", "boxes"),
            ("purchases", _("Purchases"), "inventory:purchases", "shopping-bag"),
            ("sales", _("Sales"), "inventory:sales", "shopping-cart"),
            ("suppliers", _("Suppliers"), "inventory:suppliers", "truck"),
        ],
    ),
    (
        _("Workforce"),
        [
            ("employees", _("Employees"), "workforce:employees", "contact"),
            ("attendance", _("Attendance"), "workforce:attendance", "calendar-check"),
            ("payroll", _("Payroll"), "workforce:payroll", "wallet-cards"),
            ("maintenance", _("Maintenance"), "workforce:maintenance", "wrench"),
        ],
    ),
    (
        _("Administration"),
        [
            ("settings", _("Settings"), "configuration:settings", "settings"),
            ("users", _("Users / Roles"), "configuration:users", "shield-check"),
        ],
    ),
]


def navigation_context(request):
    if not request.user.is_authenticated:
        return {"app_navigation": [], "app_navigation_groups": []}

    flat = []
    grouped = []
    for group_label, items in NAVIGATION_GROUPS:
        allowed_items = []
        for key, label, url_name, icon in items:
            if not user_can_access(request.user, key):
                continue
            item = {"key": key, "label": label, "url": reverse(url_name), "icon": icon}
            allowed_items.append(item)
            flat.append((key, label, item["url"]))
        if allowed_items:
            grouped.append({"label": group_label, "items": allowed_items})

    return {"app_navigation": flat, "app_navigation_groups": grouped}
