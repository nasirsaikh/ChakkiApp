from decimal import Decimal
from django.contrib import messages
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from apps.core.rbac import module_required
from apps.customers.models import Customer
from .forms import CustomerReceiptForm, OldUdhaarForm
from .models import Account, JournalEntry, LedgerEntry, OldUdhaar
from .services import ensure_system_accounts, post_customer_receipt, record_old_udhaar

@module_required("udhaar")
def udhaar(request: HttpRequest) -> HttpResponse:
    accounts = ensure_system_accounts()
    rows = []
    for customer in Customer.objects.filter(is_active=True).order_by("name"):
        agg = LedgerEntry.objects.filter(account=accounts["AR"], customer=customer).aggregate(d=Sum("debit"), c=Sum("credit"))
        balance = (agg["d"] or Decimal("0")) - (agg["c"] or Decimal("0"))
        if balance != 0:
            rows.append((customer, balance))
    form = CustomerReceiptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        receipt = form.save()
        post_customer_receipt(receipt, created_by=request.user)
        messages.success(request, "Receipt posted and udhaar updated.")
        return redirect("accounting:udhaar")
    return render(request, "accounting/udhaar.html", {"rows": rows, "form": form})

@module_required("old_udhaar")
def old_udhaar(request: HttpRequest) -> HttpResponse:
    form = OldUdhaarForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        record_old_udhaar(d["customer"], d["original_amount"], d["note"], created_by=request.user, opening_date=d["opening_date"])
        messages.success(request, "Opening udhaar posted.")
        return redirect("accounting:old_udhaar")
    return render(request, "accounting/old_udhaar.html", {"records": OldUdhaar.objects.select_related("customer")[:200], "form": form})

@module_required("accounts")
def accounts(request: HttpRequest) -> HttpResponse:
    ensure_system_accounts()
    account_id = request.GET.get("account")
    entries = LedgerEntry.objects.select_related("journal_entry", "account", "customer", "supplier")
    if account_id:
        entries = entries.filter(account_id=account_id)
    return render(request, "accounting/accounts.html", {"entries": entries.order_by("-journal_entry__entry_date", "-id")[:500], "accounts": Account.objects.filter(is_active=True), "selected_account": account_id})

@module_required("reports")
def reports(request: HttpRequest) -> HttpResponse:
    ensure_system_accounts()
    trial = []
    income_total = expense_total = Decimal("0")
    for account in Account.objects.filter(is_active=True).order_by("code"):
        agg = account.ledger_entries.aggregate(d=Sum("debit"), c=Sum("credit"))
        debit, credit = agg["d"] or Decimal("0"), agg["c"] or Decimal("0")
        if debit or credit:
            trial.append((account, debit, credit, debit - credit))
        if account.account_type == Account.AccountType.INCOME:
            income_total += credit - debit
        if account.account_type == Account.AccountType.EXPENSE:
            expense_total += debit - credit
    return render(request, "accounting/reports.html", {"trial": trial, "income_total": income_total, "expense_total": expense_total, "profit": income_total - expense_total})
