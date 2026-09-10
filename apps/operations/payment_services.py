from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounting.services import allocate_old_udhaar, ensure_system_accounts, old_udhaar_outstanding, post_journal
from apps.configuration.models import PaymentGatewayConfig
from .models import GrindingOrder, Invoice, OrderPayment, OrderStatusEvent


@transaction.atomic
def settle_gateway_payment(payment: OrderPayment, provider_payload: dict | None = None, created_by=None, close_order: bool = True) -> OrderPayment:
    payment = (
        OrderPayment.objects.select_for_update()
        .select_related("invoice", "order", "order__customer", "payment_gateway")
        .get(pk=payment.pk)
    )
    if payment.settlement_status == OrderPayment.SettlementStatus.SETTLED:
        return payment
    if not payment.payment_gateway_id:
        raise ValidationError("Gateway payment has no payment gateway configuration.")

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
    gateway = payment.payment_gateway
    if gateway.provider == PaymentGatewayConfig.Provider.RAZORPAY:
        receipt_account = accounts["RAZORPAY_CLEARING"]
    else:
        receipt_account = accounts["BANK"]

    journal = post_journal(
        narration=f"Gateway payment settlement {payment.payment_reference}",
        source_type="order_payment",
        source_id=payment.pk,
        created_by=created_by,
        lines=[
            {"account": receipt_account, "debit": payment.amount, "credit": 0, "customer": payment.order.customer, "memo": payment.payment_reference},
            {"account": accounts["AR"], "debit": 0, "credit": payment.amount, "customer": payment.order.customer, "memo": payment.payment_reference},
        ],
    )

    if old_amount > 0:
        allocated = allocate_old_udhaar(payment.order.customer, old_amount)
        if allocated != old_amount:
            raise ValidationError("Old udhaar allocation could not be completed.")

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
            OrderStatusEvent.objects.create(
                order=order,
                from_status=old_status,
                to_status=GrindingOrder.Status.DELIVERED,
                changed_by=created_by,
                note="Closed automatically after verified gateway payment",
            )
    order.save(update_fields=fields)
    return payment
