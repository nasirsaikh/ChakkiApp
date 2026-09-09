from __future__ import annotations
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.accounting.services import ensure_system_accounts, post_journal
from .models import InventoryItem, InventoryMovement, Purchase, Sale

@transaction.atomic
def move_stock(*, item: InventoryItem, quantity_delta: Decimal, movement_type: str, reference: str = "", notes: str = "") -> InventoryMovement:
    item = InventoryItem.objects.select_for_update().get(pk=item.pk)
    delta = Decimal(str(quantity_delta))
    new_balance = item.quantity_on_hand + delta
    if new_balance < 0:
        raise ValidationError(f"Insufficient stock for {item.name}. Available: {item.quantity_on_hand}.")
    item.quantity_on_hand = new_balance
    item.save(update_fields=["quantity_on_hand", "updated_at"])
    return InventoryMovement.objects.create(item=item, movement_type=movement_type, quantity_delta=delta, reference=reference, notes=notes, balance_after=new_balance)

@transaction.atomic
def post_purchase(purchase: Purchase, created_by=None) -> Purchase:
    purchase = Purchase.objects.select_for_update().prefetch_related("lines__item").select_related("supplier").get(pk=purchase.pk)
    if purchase.status == Purchase.Status.POSTED:
        return purchase
    total = sum((line.line_total for line in purchase.lines.all()), Decimal("0.00"))
    if total <= 0:
        raise ValidationError("Purchase requires at least one line with value.")
    if purchase.amount_paid < 0 or purchase.amount_paid > total:
        raise ValidationError("Amount paid must be between zero and the purchase total.")
    purchase.total_amount = total
    accounts = ensure_system_accounts()
    lines = [{"account": accounts["INVENTORY"], "debit": total, "credit": 0, "supplier": purchase.supplier}]
    if purchase.amount_paid > 0:
        lines.append({"account": accounts["CASH"], "debit": 0, "credit": purchase.amount_paid, "supplier": purchase.supplier})
    outstanding = total - purchase.amount_paid
    if outstanding > 0:
        lines.append({"account": accounts["AP"], "debit": 0, "credit": outstanding, "supplier": purchase.supplier})
    journal = post_journal(narration=f"Inventory purchase {purchase.purchase_number}", lines=lines, source_type="purchase", source_id=purchase.pk, entry_date=purchase.purchase_date, created_by=created_by)
    for line in purchase.lines.all():
        move_stock(item=line.item, quantity_delta=line.quantity, movement_type=InventoryMovement.MovementType.PURCHASE, reference=purchase.purchase_number)
    purchase.status = Purchase.Status.POSTED
    purchase.journal_entry = journal
    purchase.save(update_fields=["total_amount", "status", "journal_entry", "updated_at"])
    return purchase

@transaction.atomic
def post_sale(sale: Sale, created_by=None) -> Sale:
    sale = Sale.objects.select_for_update().prefetch_related("lines__item").select_related("customer").get(pk=sale.pk)
    if sale.journal_entry_id:
        return sale
    total = sum((line.line_total for line in sale.lines.all()), Decimal("0.00"))
    cost = sum(((line.quantity * line.unit_cost).quantize(Decimal("0.01")) for line in sale.lines.all()), Decimal("0.00"))
    if total <= 0:
        raise ValidationError("Sale requires at least one line.")
    accounts = ensure_system_accounts()
    debit_account = accounts["AR"] if sale.payment_method == Sale.PaymentMethod.CREDIT else accounts["CASH"]
    journal_lines = [
        {"account": debit_account, "debit": total, "credit": 0, "customer": sale.customer},
        {"account": accounts["SALES_INCOME"], "debit": 0, "credit": total, "customer": sale.customer},
    ]
    if cost > 0:
        journal_lines += [
            {"account": accounts["COGS"], "debit": cost, "credit": 0},
            {"account": accounts["INVENTORY"], "debit": 0, "credit": cost},
        ]
    journal = post_journal(narration=f"Retail sale {sale.sale_number}", lines=journal_lines, source_type="sale", source_id=sale.pk, entry_date=sale.sale_date, created_by=created_by)
    for line in sale.lines.all():
        move_stock(item=line.item, quantity_delta=-line.quantity, movement_type=InventoryMovement.MovementType.SALE, reference=sale.sale_number)
    sale.total_amount = total
    sale.journal_entry = journal
    sale.save(update_fields=["total_amount", "journal_entry", "updated_at"])
    return sale
