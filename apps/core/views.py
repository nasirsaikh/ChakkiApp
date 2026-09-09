from __future__ import annotations
import json
from datetime import timedelta
from decimal import Decimal
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from apps.accounting.models import Account, LedgerEntry
from apps.accounting.services import account_balance, ensure_system_accounts
from apps.operations.models import GrindingOrder, UtilityLedger
from .rbac import module_required

@module_required("dashboard")
def dashboard(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    start = today - timedelta(days=6)
    labels, weights, fees = [], [], []
    for offset in range(7):
        day = start + timedelta(days=offset)
        orders = GrindingOrder.objects.filter(created_at__date=day).prefetch_related("lines")
        labels.append(day.strftime("%a"))
        weights.append(float(sum((o.total_weight for o in orders), Decimal("0"))))
        fees.append(float(sum((o.total_fee for o in orders), Decimal("0"))))
    return render(request, "core/dashboard.html", {"weekly_chart_json": json.dumps({"labels": labels, "weights": weights, "fees": fees})})

@module_required("dashboard")
def dashboard_kpis(request: HttpRequest) -> HttpResponse:
    ensure_system_accounts()
    today = timezone.localdate()
    todays_orders = GrindingOrder.objects.filter(created_at__date=today).prefetch_related("lines")
    grinding_weight = sum((o.total_weight for o in todays_orders), Decimal("0"))
    income_account = Account.objects.filter(account_type=Account.AccountType.INCOME).values_list("id", flat=True)
    expense_account = Account.objects.filter(account_type=Account.AccountType.EXPENSE).values_list("id", flat=True)
    income = (LedgerEntry.objects.filter(account_id__in=income_account, journal_entry__entry_date=today).aggregate(c=Sum("credit"), d=Sum("debit"))["c"] or Decimal("0")) - (LedgerEntry.objects.filter(account_id__in=income_account, journal_entry__entry_date=today).aggregate(d=Sum("debit"))["d"] or Decimal("0"))
    expenses = (LedgerEntry.objects.filter(account_id__in=expense_account, journal_entry__entry_date=today).aggregate(d=Sum("debit"))["d"] or Decimal("0")) - (LedgerEntry.objects.filter(account_id__in=expense_account, journal_entry__entry_date=today).aggregate(c=Sum("credit"))["c"] or Decimal("0"))
    context = {
        "grinding_weight": grinding_weight,
        "net_income": income - expenses,
        "expenses": expenses,
        "cash": account_balance("CASH"),
        "udhaar": account_balance("AR"),
        "pending_jobs": GrindingOrder.objects.exclude(status__in=[GrindingOrder.Status.DELIVERED, GrindingOrder.Status.CANCELLED]).count(),
    }
    return render(request, "core/_dashboard_kpis.html", context)

def home(request: HttpRequest) -> HttpResponse:
    return redirect("core:dashboard")
