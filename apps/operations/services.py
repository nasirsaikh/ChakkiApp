from __future__ import annotations
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.accounting.services import ensure_system_accounts, post_journal
from apps.inventory.models import InventoryMovement
from apps.inventory.services import move_stock
from .models import BuybackTransaction, GrindingOrder, Invoice, OrderPayment, OrderStatusEvent, UtilityLedger

@transaction.atomic
def change_order_status(order: GrindingOrder, new_status: str, user=None, note: str = "") -> GrindingOrder:
    order = GrindingOrder.objects.select_for_update().get(pk=order.pk)
    allowed = {
        GrindingOrder.Status.INTAKE: {GrindingOrder.Status.GRINDING, GrindingOrder.Status.CANCELLED},
        GrindingOrder.Status.GRINDING: {GrindingOrder.Status.READY, GrindingOrder.Status.CANCELLED},
        GrindingOrder.Status.READY: {GrindingOrder.Status.DISPATCHED, GrindingOrder.Status.DELIVERED},
        GrindingOrder.Status.DISPATCHED: {GrindingOrder.Status.DELIVERED},
        GrindingOrder.Status.DELIVERED: set(),
        GrindingOrder.Status.CANCELLED: set(),
    }
    if new_status not in allowed.get(order.status, set()):
        raise ValidationError(f"Invalid status transition from {order.get_status_display()} to {new_status}.")
    old = order.status
    order.status = new_status
    if new_status == GrindingOrder.Status.READY:
        order.ready_at = timezone.now()
    if new_status == GrindingOrder.Status.DELIVERED:
        order.delivered_at = timezone.now()
    order.save(update_fields=["status", "ready_at", "delivered_at", "updated_at"])
    OrderStatusEvent.objects.create(order=order, from_status=old, to_status=new_status, changed_by=user, note=note)
    return order

@transaction.atomic
def finalize_invoice(order: GrindingOrder, paid_amount: Decimal = Decimal("0"), forgiven_amount: Decimal = Decimal("0"), created_by=None) -> Invoice:
    order = GrindingOrder.objects.select_for_update().prefetch_related("lines").get(pk=order.pk)
    if hasattr(order, "invoice"):
        return order.invoice
    total = sum((line.line_total for line in order.lines.all()), Decimal("0.00")).quantize(Decimal("0.01"))
    paid = Decimal(str(paid_amount)).quantize(Decimal("0.01"))
    forgiven = Decimal(str(forgiven_amount)).quantize(Decimal("0.01"))
    if paid < 0 or forgiven < 0 or paid + forgiven > total:
        raise ValidationError("Invalid paid or forgiven amount.")
    invoice = Invoice.objects.create(order=order, total_grinding_fee=total, paid_amount=Decimal("0.00"), forgiven_amount=forgiven)
    accounts = ensure_system_accounts()
    receivable = total - forgiven
    lines = [
        {"account": accounts["GRINDING_INCOME"], "debit": 0, "credit": total, "customer": order.customer, "memo": order.order_number},
    ]
    if receivable > 0:
        lines.append({"account": accounts["AR"], "debit": receivable, "credit": 0, "customer": order.customer, "memo": "Grinding receivable"})
    if forgiven > 0:
        lines.append({"account": accounts["GOODWILL_EXPENSE"], "debit": forgiven, "credit": 0, "customer": order.customer, "memo": "Customer goodwill / forgiven"})
    journal = post_journal(narration=f"Grinding invoice {invoice.invoice_number}", lines=lines, source_type="grinding_invoice", source_id=invoice.pk, created_by=created_by)
    invoice.journal_entry = journal
    invoice.save(update_fields=["journal_entry", "updated_at"])
    if paid > 0:
        payment = OrderPayment.objects.create(order=order, invoice=invoice, payment_method=OrderPayment.PaymentMethod.CASH, payment_reference=f"CASH-{invoice.invoice_number}", amount=paid)
        settle_order_payment(payment, provider_payload={"source": "invoice-cash"}, created_by=created_by, close_order=False)
    return invoice

@transaction.atomic
def settle_order_payment(payment: OrderPayment, provider_payload: dict | None = None, created_by=None, close_order: bool = True) -> OrderPayment:
    payment = OrderPayment.objects.select_for_update().select_related("invoice", "order", "order__customer").get(pk=payment.pk)
    if payment.settlement_status == OrderPayment.SettlementStatus.SETTLED:
        return payment
    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    remaining = invoice.total_grinding_fee - invoice.forgiven_amount - invoice.paid_amount
    if payment.amount > remaining:
        raise ValidationError("Payment exceeds the invoice outstanding balance.")
    accounts = ensure_system_accounts()
    journal = post_journal(
        narration=f"Payment settlement {payment.payment_reference}", source_type="order_payment", source_id=payment.pk, created_by=created_by,
        lines=[
            {"account": accounts["CASH"], "debit": payment.amount, "credit": 0, "customer": payment.order.customer, "memo": payment.payment_reference},
            {"account": accounts["AR"], "debit": 0, "credit": payment.amount, "customer": payment.order.customer, "memo": payment.payment_reference},
        ],
    )
    payment.settlement_status = OrderPayment.SettlementStatus.SETTLED
    payment.provider_payload = provider_payload or payment.provider_payload
    payment.journal_entry = journal
    payment.save(update_fields=["settlement_status", "provider_payload", "journal_entry", "settled_at", "updated_at"])
    invoice.paid_amount += payment.amount
    invoice.save()
    order = payment.order
    old_status = order.status
    order.payment_status = GrindingOrder.PaymentStatus.PAID if invoice.outstanding_amount == 0 else GrindingOrder.PaymentStatus.PARTIAL
    fields = ["payment_status", "updated_at"]
    if close_order and invoice.outstanding_amount == 0:
        order.status = GrindingOrder.Status.DELIVERED
        order.delivered_at = timezone.now()
        fields += ["status", "delivered_at"]
        OrderStatusEvent.objects.create(order=order, from_status=old_status, to_status=GrindingOrder.Status.DELIVERED, changed_by=created_by, note="Closed automatically after payment settlement")
    order.save(update_fields=fields)
    return payment

@transaction.atomic
def post_utility_cost(utility: UtilityLedger, created_by=None) -> UtilityLedger:
    if utility.journal_entry_id or utility.amount <= 0:
        return utility
    accounts = ensure_system_accounts()
    journal = post_journal(
        narration=f"Utility cost: {utility.get_utility_type_display()}", source_type="utility", source_id=utility.pk, entry_date=utility.period, created_by=created_by,
        lines=[
            {"account": accounts["UTILITY_EXPENSE"], "debit": utility.amount, "credit": 0},
            {"account": accounts["CASH"], "debit": 0, "credit": utility.amount},
        ],
    )
    utility.journal_entry = journal
    utility.save(update_fields=["journal_entry", "updated_at"])
    return utility

@transaction.atomic
def post_buyback(transaction_obj: BuybackTransaction, created_by=None) -> BuybackTransaction:
    transaction_obj = BuybackTransaction.objects.select_for_update().prefetch_related("lines__inventory_item").get(pk=transaction_obj.pk)
    if transaction_obj.journal_entry_id:
        return transaction_obj
    transaction_obj.recalculate()
    transaction_obj.save(update_fields=["buyback_value", "net_customer_payable", "updated_at"])
    value = transaction_obj.buyback_value
    fee = transaction_obj.processing_fee
    if value <= 0 and fee <= 0:
        raise ValidationError("Buyback has no accounting value.")
    accounts = ensure_system_accounts()
    lines = []
    if value > 0:
        lines.extend([
            {"account": accounts["INVENTORY"], "debit": value, "credit": 0, "customer": transaction_obj.customer},
            {"account": accounts["BUYBACK_PAYABLE"], "debit": 0, "credit": value, "customer": transaction_obj.customer},
        ])
    if fee > 0:
        payable_offset = min(value, fee)
        if payable_offset > 0:
            lines.append({"account": accounts["BUYBACK_PAYABLE"], "debit": payable_offset, "credit": 0, "customer": transaction_obj.customer})
        excess_fee = fee - payable_offset
        if excess_fee > 0:
            lines.append({"account": accounts["AR"], "debit": excess_fee, "credit": 0, "customer": transaction_obj.customer})
        lines.append({"account": accounts["GRINDING_INCOME"], "debit": 0, "credit": fee, "customer": transaction_obj.customer})
    net_payable = value - fee
    if net_payable > 0:
        lines.extend([
            {"account": accounts["BUYBACK_PAYABLE"], "debit": net_payable, "credit": 0, "customer": transaction_obj.customer},
            {"account": accounts["CASH"], "debit": 0, "credit": net_payable, "customer": transaction_obj.customer},
        ])
    journal = post_journal(narration=f"Buyback {transaction_obj.reference}", lines=lines, source_type="buyback", source_id=transaction_obj.pk, created_by=created_by)
    for line in transaction_obj.lines.all():
        move_stock(item=line.inventory_item, quantity_delta=line.quantity_kg, movement_type=InventoryMovement.MovementType.BUYBACK, reference=transaction_obj.reference, notes=f"Customer buyback: {line.get_product_type_display()}")
    transaction_obj.journal_entry = journal
    transaction_obj.save(update_fields=["journal_entry", "updated_at"])
    return transaction_obj

