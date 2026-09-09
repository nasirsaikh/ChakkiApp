from __future__ import annotations
from decimal import Decimal
import uuid
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from .models import Account, CustomerReceipt, JournalEntry, LedgerEntry, OldUdhaar

SYSTEM_ACCOUNTS = {
    "CASH": ("1000", "Cash Book", Account.AccountType.ASSET),
    "AR": ("1100", "Accounts Receivable (Udhaar)", Account.AccountType.ASSET),
    "INVENTORY": ("1200", "Inventory Asset", Account.AccountType.ASSET),
    "AP": ("2000", "Accounts Payable (Suppliers)", Account.AccountType.LIABILITY),
    "BUYBACK_PAYABLE": ("2100", "Customer Buyback Payable", Account.AccountType.LIABILITY),
    "OPENING_EQUITY": ("3000", "Opening Balance Equity", Account.AccountType.EQUITY),
    "GRINDING_INCOME": ("4000", "Grinding Income", Account.AccountType.INCOME),
    "SALES_INCOME": ("4100", "Retail Sales Income", Account.AccountType.INCOME),
    "GOODWILL_EXPENSE": ("5000", "Expense: Customer Goodwill/Forgiven", Account.AccountType.EXPENSE),
    "COGS": ("5100", "Cost of Goods Sold", Account.AccountType.EXPENSE),
    "UTILITY_EXPENSE": ("5200", "Utility Expense", Account.AccountType.EXPENSE),
    "WAGE_EXPENSE": ("5300", "Wage and Payroll Expense", Account.AccountType.EXPENSE),
    "MAINTENANCE_EXPENSE": ("5400", "Maintenance Expense", Account.AccountType.EXPENSE),
    "GENERAL_EXPENSE": ("5900", "General Operating Expense", Account.AccountType.EXPENSE),
}


def ensure_system_accounts() -> dict[str, Account]:
    result = {}
    for key, (code, name, account_type) in SYSTEM_ACCOUNTS.items():
        account, _ = Account.objects.get_or_create(system_key=key, defaults={"code": code, "name": name, "account_type": account_type})
        result[key] = account
    return result


def _next_journal_number() -> str:
    today = timezone.localdate()
    return f"JE-{today:%Y%m%d}-{uuid.uuid4().hex[:10].upper()}"


def _signed_delta(account: Account, debit: Decimal, credit: Decimal) -> Decimal:
    if account.account_type in {Account.AccountType.ASSET, Account.AccountType.EXPENSE}:
        return debit - credit
    return credit - debit


@transaction.atomic
def post_journal(*, narration: str, lines: list[dict], source_type: str = "", source_id: int | None = None, entry_date=None, created_by=None) -> JournalEntry:
    if not lines or len(lines) < 2:
        raise ValidationError("A journal entry requires at least two lines.")
    total_debit = sum((Decimal(str(line.get("debit", 0))) for line in lines), Decimal("0"))
    total_credit = sum((Decimal(str(line.get("credit", 0))) for line in lines), Decimal("0"))
    if total_debit <= 0 or total_debit != total_credit:
        raise ValidationError(f"Journal is not balanced: debit {total_debit} != credit {total_credit}.")
    journal = JournalEntry.objects.create(entry_number=_next_journal_number(), entry_date=entry_date or timezone.localdate(), narration=narration, source_type=source_type, source_id=source_id, created_by=created_by)
    account_ids = sorted({line["account"].pk for line in lines})
    accounts = {a.pk: a for a in Account.objects.select_for_update().filter(pk__in=account_ids)}
    balances = {}
    for account_id in account_ids:
        previous = LedgerEntry.objects.filter(account_id=account_id).order_by("-id").values_list("transactional_balance", flat=True).first()
        balances[account_id] = previous or Decimal("0.00")
    for line in lines:
        account = accounts[line["account"].pk]
        debit = Decimal(str(line.get("debit", 0))).quantize(Decimal("0.01"))
        credit = Decimal(str(line.get("credit", 0))).quantize(Decimal("0.01"))
        balances[account.pk] += _signed_delta(account, debit, credit)
        LedgerEntry.objects.create(journal_entry=journal, account=account, customer=line.get("customer"), supplier=line.get("supplier"), debit=debit, credit=credit, transactional_balance=balances[account.pk], line_memo=line.get("memo", ""))
    return journal


def account_balance(system_key: str) -> Decimal:
    account = Account.objects.filter(system_key=system_key).first()
    if not account:
        return Decimal("0.00")
    value = LedgerEntry.objects.filter(account=account).order_by("-id").values_list("transactional_balance", flat=True).first()
    return value or Decimal("0.00")


def customer_outstanding(customer) -> Decimal:
    accounts = ensure_system_accounts()
    debits = LedgerEntry.objects.filter(account=accounts["AR"], customer=customer).aggregate(v=models.Sum("debit"))["v"] or Decimal("0")
    credits = LedgerEntry.objects.filter(account=accounts["AR"], customer=customer).aggregate(v=models.Sum("credit"))["v"] or Decimal("0")
    return debits - credits


def old_udhaar_outstanding(customer) -> Decimal:
    records = OldUdhaar.objects.filter(customer=customer)
    original = records.aggregate(v=models.Sum("original_amount"))["v"] or Decimal("0.00")
    settled = records.aggregate(v=models.Sum("settled_amount"))["v"] or Decimal("0.00")
    return max(original - settled, Decimal("0.00"))


@transaction.atomic
def allocate_old_udhaar(customer, amount: Decimal) -> Decimal:
    remaining = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
    if remaining < 0:
        raise ValidationError("Old udhaar allocation cannot be negative.")
    requested = remaining
    old_records = OldUdhaar.objects.select_for_update().filter(customer=customer).order_by("opening_date", "id")
    for old_record in old_records:
        if remaining <= 0:
            break
        available = old_record.original_amount - old_record.settled_amount
        if available <= 0:
            continue
        allocation = min(remaining, available)
        old_record.settled_amount += allocation
        old_record.save(update_fields=["settled_amount", "updated_at"])
        remaining -= allocation
    if remaining > 0:
        raise ValidationError("Old udhaar allocation exceeds the customer's outstanding old balance.")
    return requested


@transaction.atomic
def post_customer_receipt(receipt: CustomerReceipt, created_by=None) -> CustomerReceipt:
    if receipt.journal_entry_id:
        return receipt
    if receipt.amount <= 0:
        raise ValidationError("Receipt amount must be greater than zero.")
    accounts = ensure_system_accounts()
    journal = post_journal(narration=f"Customer receipt from {receipt.customer.name}", source_type="customer_receipt", source_id=receipt.pk, entry_date=receipt.receipt_date, created_by=created_by, lines=[{"account": accounts["CASH"], "debit": receipt.amount, "credit": 0, "customer": receipt.customer}, {"account": accounts["AR"], "debit": 0, "credit": receipt.amount, "customer": receipt.customer}])
    receipt.journal_entry = journal
    receipt.save(update_fields=["journal_entry", "updated_at"])
    allocate_old_udhaar(receipt.customer, receipt.amount)
    return receipt


@transaction.atomic
def record_old_udhaar(customer, amount: Decimal, note: str = "Opening balance", created_by=None, opening_date=None) -> OldUdhaar:
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValidationError("Opening balance must be greater than zero.")
    old = OldUdhaar.objects.create(customer=customer, original_amount=amount, note=note, opening_date=opening_date or timezone.localdate())
    accounts = ensure_system_accounts()
    journal = post_journal(narration=f"Opening udhaar for {customer.name}", source_type="old_udhaar", source_id=old.pk, entry_date=old.opening_date, created_by=created_by, lines=[{"account": accounts["AR"], "debit": amount, "credit": 0, "customer": customer}, {"account": accounts["OPENING_EQUITY"], "debit": 0, "credit": amount, "customer": customer}])
    old.journal_entry = journal
    old.save(update_fields=["journal_entry", "updated_at"])
    return old
