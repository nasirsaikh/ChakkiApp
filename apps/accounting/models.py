from __future__ import annotations
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from apps.core.models import TimeStampedModel

class Account(TimeStampedModel):
    class AccountType(models.TextChoices):
        ASSET = "ASSET", "Asset"
        LIABILITY = "LIABILITY", "Liability"
        EQUITY = "EQUITY", "Equity"
        INCOME = "INCOME", "Income"
        EXPENSE = "EXPENSE", "Expense"

    code = models.CharField(max_length=20, unique=True, verbose_name="Account code")
    name = models.CharField(max_length=120, unique=True, verbose_name="Account name")
    account_type = models.CharField(max_length=12, choices=AccountType.choices, verbose_name="Account type")
    system_key = models.CharField(max_length=40, unique=True, null=True, blank=True, verbose_name="System key")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        ordering = ["code"]
        verbose_name = "Ledger account"
        verbose_name_plural = "Ledger accounts"

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

class JournalEntry(TimeStampedModel):
    entry_number = models.CharField(max_length=30, unique=True, verbose_name="Journal number")
    entry_date = models.DateField(default=timezone.localdate, db_index=True, verbose_name="Entry date")
    narration = models.CharField(max_length=255, verbose_name="Narration")
    source_type = models.CharField(max_length=50, blank=True, verbose_name="Source type")
    source_id = models.PositiveBigIntegerField(null=True, blank=True, verbose_name="Source ID")
    posted = models.BooleanField(default=True, verbose_name="Posted")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="chakki_journal_entries")

    class Meta:
        ordering = ["-entry_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["source_type", "source_id"], condition=Q(source_type__gt="", source_id__isnull=False), name="unique_accounting_source")]

    def __str__(self) -> str:
        return self.entry_number

class LedgerEntry(TimeStampedModel):
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines", verbose_name="Journal entry")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="ledger_entries", verbose_name="Ledger account")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="ledger_entries", verbose_name="Customer")
    supplier = models.ForeignKey("inventory.Supplier", on_delete=models.PROTECT, null=True, blank=True, related_name="ledger_entries", verbose_name="Supplier")
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), verbose_name="Debit")
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), verbose_name="Credit")
    transactional_balance = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"), verbose_name="Transactional balance")
    line_memo = models.CharField(max_length=255, blank=True, verbose_name="Line memo")

    class Meta:
        ordering = ["journal_entry__entry_date", "id"]
        indexes = [models.Index(fields=["account", "id"]), models.Index(fields=["customer", "id"]), models.Index(fields=["supplier", "id"])]
        constraints = [
            models.CheckConstraint(condition=Q(debit__gte=0) & Q(credit__gte=0), name="ledger_non_negative"),
            models.CheckConstraint(condition=(Q(debit__gt=0, credit=0) | Q(credit__gt=0, debit=0)), name="ledger_exactly_one_side"),
        ]

    def clean(self) -> None:
        if (self.debit > 0 and self.credit > 0) or (self.debit <= 0 and self.credit <= 0):
            raise ValidationError("Exactly one of debit or credit must be greater than zero.")

    def __str__(self) -> str:
        return f"{self.journal_entry.entry_number} / {self.account.name}"

class CustomerReceipt(TimeStampedModel):
    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        UPI = "UPI", "UPI / QR"
        BANK = "BANK", "Bank transfer"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="receipts", verbose_name="Customer")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Receipt amount")
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH, verbose_name="Payment method")
    reference = models.CharField(max_length=80, blank=True, verbose_name="Reference")
    receipt_date = models.DateField(default=timezone.localdate, verbose_name="Receipt date")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="customer_receipt", null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True, verbose_name="Notes")

    class Meta:
        ordering = ["-receipt_date", "-id"]

    def __str__(self) -> str:
        return f"{self.customer} - {self.amount}"

class OldUdhaar(TimeStampedModel):
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="old_udhaar_records", verbose_name="Customer")
    original_amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Original opening amount")
    settled_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Settled amount")
    opening_date = models.DateField(default=timezone.localdate, verbose_name="Opening date")
    note = models.CharField(max_length=255, blank=True, verbose_name="Note")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True, related_name="old_udhaar")

    class Meta:
        ordering = ["-opening_date", "-id"]

    @property
    def outstanding_amount(self) -> Decimal:
        return max(self.original_amount - self.settled_amount, Decimal("0.00"))

    def __str__(self) -> str:
        return f"Old Udhaar {self.customer} - {self.outstanding_amount}"
