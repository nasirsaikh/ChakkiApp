from __future__ import annotations
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.accounting.services import allocate_old_udhaar, ensure_system_accounts, old_udhaar_outstanding, post_journal
from apps.inventory.models import InventoryMovement
from apps.inventory.services import move_stock
from .models import BuybackTransaction, GrindingOrder, Invoice, OrderPayment, OrderStatusEvent, UtilityLedger

MONEY = Decimal("0.01")


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
    total = sum((line.line_total for line in order.lines.all()), Decimal("0.00")).quantize(MONEY)
    paid = Decimal(str(paid_amount)).quantize(MONEY)
    forgiven = Decimal(str(forgiven_amount)).quantize(MONEY)
    if paid < 0 or forgiven < 0 or paid + forgiven > total:
        raise ValidationError("Invalid paid or forgiven amount.")
    invoice = Invoice.objects.create(order=order, total_grinding_fee=total, paid_amount=Decimal("0.00"), forgiven_amount=forgiven)
    accounts = ensure_system_accounts()
    receivable = total - forgiven
    lines = [{"account": accounts["GRINDING_INCOME"], "debit": 0, "credit": total, "customer": order.customer, "memo": order.order_number}]
    if receivable > 0:
        lines.append({"account": accounts["AR"], "debit": receivable, "credit": 0, "customer": order.customer, "memo": "Grinding receivable"})
    if forgiven > 0:
        lines.append({"account": accounts["GOODWILL_EXPENSE"], "debit": forgiven, "credit": 0, "customer": order.customer, "memo": "Customer goodwill / forgiven"})
    journal = post_journal(narration=f"Grinding invoice {invoice.invoice_number}", lines=lines, source_type="grinding_invoice", source_id=invoice.pk, created_by=created_by)
    invoice.journal_entry = journal
    invoice.save(update_fields=["journal_entry", "updated_at"])
    if paid > 0:
        payment = OrderPayment.objects.create(order=order, invoice=invoice, payment_method=OrderPayment.PaymentMethod.CASH, payment_reference=f"CASH-{invoice.invoice_number}", amount=paid, current_invoice_amount=paid)
        settle_order_payment(payment, provider_payload={"source": "invoice-cash"}, created_by=created_by, close_order=False)
    return invoice


@transaction.atomic
def revise_invoice_total(invoice: Invoice, new_total: Decimal, created_by=None, narration: str = "Grinding rate/weight revision") -> Invoice:
    invoice = Invoice.objects.select_for_update().select_related("order", "order__customer").get(pk=invoice.pk)
    new_total = Decimal(str(new_total)).quantize(MONEY)
    if invoice.status == Invoice.Status.VOID:
        raise ValidationError("A void invoice cannot be revised.")
    if new_total < invoice.paid_amount + invoice.forgiven_amount:
        raise ValidationError("Revised grinding amount cannot be less than amounts already paid or forgiven.")
    delta = new_total - invoice.total_grinding_fee
    if delta == 0:
        return invoice
    accounts = ensure_system_accounts()
    customer = invoice.order.customer
    if delta > 0:
        lines = [
            {"account": accounts["AR"], "debit": delta, "credit": 0, "customer": customer, "memo": invoice.invoice_number},
            {"account": accounts["GRINDING_INCOME"], "debit": 0, "credit": delta, "customer": customer, "memo": invoice.invoice_number},
        ]
    else:
        value = -delta
        lines = [
            {"account": accounts["GRINDING_INCOME"], "debit": value, "credit": 0, "customer": customer, "memo": invoice.invoice_number},
            {"account": accounts["AR"], "debit": 0, "credit": value, "customer": customer, "memo": invoice.invoice_number},
        ]
    post_journal(narration=f"{narration}: {invoice.invoice_number}", lines=lines, source_type="grinding_invoice_revision", source_id=None, created_by=created_by)
    invoice.total_grinding_fee = new_total
    invoice.save()
    return invoice


@transaction.atomic
def add_invoice_forgiveness(invoice: Invoice, amount: Decimal, created_by=None) -> Invoice:
    invoice = Invoice.objects.select_for_update().select_related("order", "order__customer").get(pk=invoice.pk)
    amount = Decimal(str(amount or 0)).quantize(MONEY)
    if amount <= 0:
        return invoice
    if amount > invoice.outstanding_amount:
        raise ValidationError("Forgiven amount cannot exceed the current invoice outstanding amount.")
    accounts = ensure_system_accounts()
    customer = invoice.order.customer
    post_journal(
        narration=f"Customer goodwill / forgiveness {invoice.invoice_number}",
        lines=[
            {"account": accounts["GOODWILL_EXPENSE"], "debit": amount, "credit": 0, "customer": customer, "memo": invoice.invoice_number},
            {"account": accounts["AR"], "debit": 0, "credit": amount, "customer": customer, "memo": invoice.invoice_number},
        ],
        source_type="invoice_forgiveness", source_id=None, created_by=created_by,
    )
    invoice.forgiven_amount += amount
    invoice.save()
    return invoice


@transaction.atomic
def void_intake_order(order: GrindingOrder, created_by=None) -> GrindingOrder:
    order = GrindingOrder.objects.select_for_update().select_related("customer").get(pk=order.pk)
    if order.status != GrindingOrder.Status.INTAKE:
        raise ValidationError("Only an Intake order can be deleted/cancelled.")
    invoice = Invoice.objects.select_for_update().filter(order=order).first()
    if order.payments.filter(settlement_status=OrderPayment.SettlementStatus.SETTLED).exists():
        raise ValidationError("This intake already has a settled payment and cannot be deleted.")
    if invoice and (invoice.paid_amount > 0 or invoice.forgiven_amount > 0):
        raise ValidationError("This intake already has payment/forgiveness activity and cannot be deleted.")
    if invoice and invoice.status != Invoice.Status.VOID and invoice.total_grinding_fee > 0:
        accounts = ensure_system_accounts()
        amount = invoice.total_grinding_fee
        post_journal(
            narration=f"Void intake {order.order_number}",
            lines=[
                {"account": accounts["GRINDING_INCOME"], "debit": amount, "credit": 0, "customer": order.customer, "memo": "Intake cancelled"},
                {"account": accounts["AR"], "debit": 0, "credit": amount, "customer": order.customer, "memo": "Intake cancelled"},
            ],
            source_type="grinding_invoice_void", source_id=invoice.pk, created_by=created_by,
        )
        invoice.status = Invoice.Status.VOID
        invoice.outstanding_amount = Decimal("0.00")
        invoice.save(update_fields=["status", "outstanding_amount", "updated_at"])
    old = order.status
    order.status = GrindingOrder.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    OrderStatusEvent.objects.create(order=order, from_status=old, to_status=GrindingOrder.Status.CANCELLED, changed_by=created_by, note="Intake deleted/cancelled before grinding")
    return order


@transaction.atomic
def settle_order_payment(payment: OrderPayment, provider_payload: dict | None = None, created_by=None, close_order: bool = True) -> OrderPayment:
    payment = OrderPayment.objects.select_for_update().select_related("invoice", "order", "order__customer").get(pk=payment.pk)
    if payment.settlement_status == OrderPayment.SettlementStatus.SETTLED:
        return payment
    invoice = Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    current_amount = payment.current_invoice_amount or Decimal("0.00")
    old_amount = payment.old_udhaar_amount or Decimal("0.00")
    if current_amount + old_amount != payment.amount:
        raise ValidationError("Payment allocation does not equal the payment amount.")
    if current_amount > invoice.outstanding_amount:
        raise ValidationError("Current payment exceeds the invoice outstanding balance.")
    if old_amount > old_udhaar_outstanding(payment.order.customer):
        raise ValidationError("Old udhaar payment exceeds the old outstanding balance.")
    accounts = ensure_system_accounts()
    journal = post_journal(
        narration=f"Payment settlement {payment.payment_reference}", source_type="order_payment", source_id=payment.pk, created_by=created_by,
        lines=[
            {"account": accounts["CASH"], "debit": payment.amount, "credit": 0, "customer": payment.order.customer, "memo": payment.payment_reference},
            {"account": accounts["AR"], "debit": 0, "credit": payment.amount, "customer": payment.order.customer, "memo": payment.payment_reference},
        ],
    )
    if old_amount > 0:
        allocate_old_udhaar(payment.order.customer, old_amount)
    payment.settlement_status = OrderPayment.SettlementStatus.SETTLED
    payment.provider_payload = provider_payload or payment.provider_payload
    payment.journal_entry = journal
    payment.save(update_fields=["settlement_status", "provider_payload", "journal_entry", "settled_at", "updated_at"])
    if current_amount > 0:
        invoice.paid_amount += current_amount
        invoice.save()
    order = payment.order
    old_status = order.status
    order.payment_status = GrindingOrder.PaymentStatus.PAID if invoice.outstanding_amount == 0 else GrindingOrder.PaymentStatus.PARTIAL
    fields = ["payment_status", "updated_at"]
    if close_order and invoice.outstanding_amount == 0:
        order.status = GrindingOrder.Status.DELIVERED
        order.delivered_at = timezone.now()
        fields += ["status", "delivered_at"]
        if old_status != GrindingOrder.Status.DELIVERED:
            OrderStatusEvent.objects.create(order=order, from_status=old_status, to_status=GrindingOrder.Status.DELIVERED, changed_by=created_by, note="Closed automatically after payment settlement")
    order.save(update_fields=fields)
    return payment


@transaction.atomic
def post_utility_cost(utility: UtilityLedger, created_by=None) -> UtilityLedger:
    if utility.journal_entry_id or utility.amount <= 0:
        return utility
    accounts = ensure_system_accounts()
    journal = post_journal(narration=f"Utility cost: {utility.get_utility_type_display()}", source_type="utility", source_id=utility.pk, entry_date=utility.period, created_by=created_by, lines=[{"account": accounts["UTILITY_EXPENSE"], "debit": utility.amount, "credit": 0}, {"account": accounts["CASH"], "debit": 0, "credit": utility.amount}])
    utility.journal_entry = journal
    utility.save(update_fields=["journal_entry", "updated_at"])
    return utility


@transaction.atomic
def post_buyback(transaction_obj: BuybackTransaction, created_by=None) -> BuybackTransaction:
    transaction_obj = BuybackTransaction.objects.select_for_update().select_related("order", "customer").prefetch_related("lines__inventory_item").get(pk=transaction_obj.pk)
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

    if fee > 0:
        if value > 0:
            lines.extend([
                {"account": accounts["INVENTORY"], "debit": value, "credit": 0, "customer": transaction_obj.customer},
                {"account": accounts["BUYBACK_PAYABLE"], "debit": 0, "credit": value, "customer": transaction_obj.customer},
            ])
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
            transaction_obj.cash_paid_amount = net_payable
    else:
        if value <= 0:
            raise ValidationError("Buyback value must be greater than zero.")
        lines.extend([
            {"account": accounts["INVENTORY"], "debit": value, "credit": 0, "customer": transaction_obj.customer},
            {"account": accounts["BUYBACK_PAYABLE"], "debit": 0, "credit": value, "customer": transaction_obj.customer},
        ])
        remaining = value
        invoice = Invoice.objects.select_for_update().filter(order=transaction_obj.order).first() if transaction_obj.order_id else None
        old_outstanding = old_udhaar_outstanding(transaction_obj.customer)
        current_outstanding = invoice.outstanding_amount if invoice and invoice.status != Invoice.Status.VOID else Decimal("0.00")
        current_adjust = Decimal("0.00")
        old_adjust = Decimal("0.00")
        cash_pay = Decimal("0.00")
        target = transaction_obj.adjustment_target

        if target in {BuybackTransaction.AdjustmentTarget.AUTO, BuybackTransaction.AdjustmentTarget.CURRENT} and remaining > 0:
            current_adjust = min(remaining, current_outstanding)
            remaining -= current_adjust
        if target in {BuybackTransaction.AdjustmentTarget.AUTO, BuybackTransaction.AdjustmentTarget.OLD} and remaining > 0:
            old_adjust = min(remaining, old_outstanding)
            remaining -= old_adjust
        if target == BuybackTransaction.AdjustmentTarget.CASH:
            cash_pay = remaining
            remaining = Decimal("0.00")
        elif target in {BuybackTransaction.AdjustmentTarget.AUTO, BuybackTransaction.AdjustmentTarget.CURRENT, BuybackTransaction.AdjustmentTarget.OLD} and remaining > 0:
            cash_pay = remaining
            remaining = Decimal("0.00")

        ar_adjust = current_adjust + old_adjust
        if ar_adjust > 0:
            lines.extend([
                {"account": accounts["BUYBACK_PAYABLE"], "debit": ar_adjust, "credit": 0, "customer": transaction_obj.customer},
                {"account": accounts["AR"], "debit": 0, "credit": ar_adjust, "customer": transaction_obj.customer},
            ])
        if cash_pay > 0:
            lines.extend([
                {"account": accounts["BUYBACK_PAYABLE"], "debit": cash_pay, "credit": 0, "customer": transaction_obj.customer},
                {"account": accounts["CASH"], "debit": 0, "credit": cash_pay, "customer": transaction_obj.customer},
            ])
        if invoice and current_adjust > 0:
            invoice.paid_amount += current_adjust
            invoice.save()
        if old_adjust > 0:
            allocate_old_udhaar(transaction_obj.customer, old_adjust)
        transaction_obj.adjusted_current_amount = current_adjust
        transaction_obj.adjusted_old_amount = old_adjust
        transaction_obj.cash_paid_amount = cash_pay

    journal = post_journal(narration=f"Buyback {transaction_obj.reference}", lines=lines, source_type="buyback", source_id=transaction_obj.pk, created_by=created_by)
    for line in transaction_obj.lines.all():
        move_stock(item=line.inventory_item, quantity_delta=line.quantity_kg, movement_type=InventoryMovement.MovementType.BUYBACK, reference=transaction_obj.reference, notes=f"Customer buyback: {line.get_product_type_display()}")
    transaction_obj.journal_entry = journal
    transaction_obj.save(update_fields=["journal_entry", "adjusted_current_amount", "adjusted_old_amount", "cash_paid_amount", "updated_at"])
    if transaction_obj.order_id and hasattr(transaction_obj.order, "invoice"):
        transaction_obj.order.invoice.refresh_from_db()
        transaction_obj.order.payment_status = GrindingOrder.PaymentStatus.PAID if transaction_obj.order.invoice.outstanding_amount == 0 else GrindingOrder.PaymentStatus.PARTIAL
        transaction_obj.order.save(update_fields=["payment_status", "updated_at"])
    return transaction_obj
