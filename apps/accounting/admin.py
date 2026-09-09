from django.contrib import admin

from .models import Account, CustomerReceipt, JournalEntry, LedgerEntry, OldUdhaar


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "account_type", "system_key", "is_active")
    search_fields = ("code", "name", "system_key")
    list_filter = ("account_type", "is_active")


class ImmutablePostedAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(JournalEntry)
class JournalEntryAdmin(ImmutablePostedAdmin):
    list_display = ("entry_number", "entry_date", "narration", "source_type", "source_id", "created_at")
    search_fields = ("entry_number", "narration", "source_type")
    list_filter = ("entry_date", "source_type")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ImmutablePostedAdmin):
    list_display = ("journal_entry", "account", "customer", "supplier", "debit", "credit", "transactional_balance")
    search_fields = ("journal_entry__entry_number", "account__name", "customer__name", "supplier__name")
    list_filter = ("account",)


@admin.register(CustomerReceipt)
class CustomerReceiptAdmin(admin.ModelAdmin):
    list_display = ("customer", "amount", "payment_method", "reference", "receipt_date", "journal_entry")
    search_fields = ("customer__name", "reference")
    list_filter = ("payment_method", "receipt_date")


@admin.register(OldUdhaar)
class OldUdhaarAdmin(admin.ModelAdmin):
    list_display = ("customer", "opening_date", "original_amount", "settled_amount", "outstanding_amount")
    search_fields = ("customer__name", "note")
    list_filter = ("opening_date",)
