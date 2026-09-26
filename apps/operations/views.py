from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import qrcode
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounting.models import OldUdhaar
from apps.accounting.services import old_udhaar_outstanding
from apps.configuration.models import ChakkiSettings, PaymentGatewayConfig
from apps.core.rbac import module_required
from .forms import BillSettlementForm, BuybackForm, GrindingIntakeForm, OrderBuybackForm, PaymentRequestForm, ProductionLogForm, RateCardForm, UtilityLedgerForm, WastageLogForm
from .models import BuybackTransaction, GrindingOrder, Invoice, OrderPayment, ProductionLog, RateCard, UtilityLedger, WastageLog
from .payment_gateways.razorpay_checkout import render_razorpay_checkout
from .services import add_invoice_forgiveness, change_order_status, finalize_invoice, post_buyback, post_utility_cost, revise_invoice_total, settle_order_payment, void_intake_order


def _qr_data_uri(value: str) -> str:
    image = qrcode.make(value)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _verify_gateway_signature(gateway: PaymentGatewayConfig, request: HttpRequest, raw: bytes) -> bool:
    try:
        secret = gateway.webhook_secret
    except ImproperlyConfigured:
        return False
    if not secret:
        return False
    signature = request.headers.get(gateway.webhook_signature_header, "").strip()
    if signature.lower().startswith("sha256="):
        signature = signature.split("=", 1)[1].strip()
    if not signature:
        return False
    if gateway.signature_algorithm == PaymentGatewayConfig.SignatureAlgorithm.HMAC_SHA256:
        expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.lower(), expected.lower())
    return False


def _payment_qr_response(request: HttpRequest, order: GrindingOrder, payment: OrderPayment, gateway: PaymentGatewayConfig) -> HttpResponse:
    chakki = ChakkiSettings.load()
    params = {
        "pa": gateway.upi_vpa,
        "pn": gateway.merchant_name or chakki.brand_name,
        "am": f"{payment.amount:.2f}",
        "cu": gateway.currency_code or chakki.currency_code,
        "tn": payment.payment_reference,
        "tr": payment.payment_reference,
    }
    upi_payload = "upi://pay?" + urlencode(params)
    return render(request, "operations/payment_qr.html", {"payment": payment, "order": order, "gateway": gateway, "qr_data_uri": _qr_data_uri(upi_payload), "upi_payload": upi_payload})


def _payment_gateway_response(request: HttpRequest, order: GrindingOrder, payment: OrderPayment, gateway: PaymentGatewayConfig) -> HttpResponse:
    if gateway.provider == PaymentGatewayConfig.Provider.RAZORPAY:
        try:
            return render_razorpay_checkout(request, order, payment, gateway)
        except Exception:
            payment.delete()
            messages.error(request, "Razorpay order creation failed. Check the Test/Live API keys and gateway configuration in Django Admin.")
            return redirect("operations:order_detail", pk=order.pk)
    return _payment_qr_response(request, order, payment, gateway)


@module_required("grinding")
def grinding_board(request: HttpRequest) -> HttpResponse:
    orders = GrindingOrder.objects.select_related("customer").prefetch_related("lines", "payments").exclude(status=GrindingOrder.Status.CANCELLED)[:200]
    if request.headers.get("HX-Request") == "true" and request.GET.get("partial"):
        return render(request, "operations/_grinding_board.html", {"orders": orders})
    return render(request, "operations/grinding_board.html", {"orders": orders})


@module_required("grinding")
def grinding_create(request: HttpRequest) -> HttpResponse:
    form = GrindingIntakeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        order = form.save(request.user)
        finalize_invoice(order, created_by=request.user)
        messages.success(request, f"Order {order.order_number} created. Payment can be recorded when the customer pays.")
        return redirect("operations:order_detail", pk=order.pk)
    rate_matrix = {str(rate.pk): str(rate.system_rate_per_kg) for rate in RateCard.objects.filter(is_active=True)}
    return render(request, "operations/grinding_form.html", {"form": form, "rate_matrix": rate_matrix, "edit_mode": False})


@module_required("grinding")
def grinding_edit(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(GrindingOrder.objects.prefetch_related("lines", "payments"), pk=pk)
    if order.status != GrindingOrder.Status.INTAKE:
        messages.error(request, "Only orders still in Intake can be edited.")
        return redirect("operations:order_detail", pk=pk)
    if order.payments.filter(settlement_status=OrderPayment.SettlementStatus.SETTLED).exists():
        messages.error(request, "This intake has a settled payment. Reverse/adjust the payment before editing the intake.")
        return redirect("operations:order_detail", pk=pk)
    form = GrindingIntakeForm(request.POST or None, order=order)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            order = form.save(request.user)
            invoice = Invoice.objects.select_for_update().get(order=order)
            revise_invoice_total(invoice, order.total_fee, created_by=request.user, narration="Intake correction")
        messages.success(request, f"Intake {order.order_number} updated.")
        return redirect("operations:order_detail", pk=order.pk)
    rate_matrix = {str(rate.pk): str(rate.system_rate_per_kg) for rate in RateCard.objects.filter(is_active=True)}
    return render(request, "operations/grinding_form.html", {"form": form, "rate_matrix": rate_matrix, "edit_mode": True, "order": order})


@module_required("grinding")
@require_POST
def grinding_delete(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(GrindingOrder, pk=pk)
    try:
        void_intake_order(order, created_by=request.user)
        messages.success(request, f"Intake {order.order_number} deleted/cancelled before grinding. Accounting was safely reversed.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("operations:grinding_board")


def _order_payment_context(order: GrindingOrder, bound_settlement_form=None, bound_buyback_form=None) -> dict:
    invoice = getattr(order, "invoice", None)
    old_records = OldUdhaar.objects.filter(customer=order.customer, original_amount__gt=F("settled_amount")).order_by("opening_date", "id")
    old_total = old_udhaar_outstanding(order.customer)
    current_total = Invoice.objects.filter(order__customer=order.customer).exclude(status=Invoice.Status.VOID).aggregate(v=Sum("outstanding_amount"))["v"] or Decimal("0.00")
    settlement_form = bound_settlement_form or BillSettlementForm(order=order, invoice=invoice, old_udhaar_total=old_total)
    buyback_form = bound_buyback_form or OrderBuybackForm(order=order)
    return {
        "order": order,
        "invoice": invoice,
        "settlement_form": settlement_form,
        "buyback_form": buyback_form,
        "has_payment_gateway": settlement_form.fields["provider"].queryset.exists(),
        "old_udhaar_records": old_records,
        "old_udhaar_total": old_total,
        "current_udhaar_total": current_total,
        "buyback_has_atta": buyback_form.has_atta,
        "buyback_has_khal": buyback_form.has_khal,
        "atta_system_rate": buyback_form.atta_system_rate,
        "khal_system_rate": buyback_form.khal_system_rate,
    }


@module_required("grinding")
def order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(GrindingOrder.objects.select_related("customer").prefetch_related("lines__rate_card", "payments", "status_events", "buybacks__lines"), pk=pk)
    return render(request, "operations/order_detail.html", _order_payment_context(order))


@module_required("grinding")
@require_POST
def settle_bill(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(GrindingOrder.objects.select_related("customer").prefetch_related("lines__rate_card"), pk=pk)
    invoice = get_object_or_404(Invoice, order=order)
    old_total = old_udhaar_outstanding(order.customer)
    form = BillSettlementForm(request.POST, order=order, invoice=invoice, old_udhaar_total=old_total)
    if not form.is_valid():
        return render(request, "operations/order_detail.html", _order_payment_context(order, bound_settlement_form=form), status=400)
    data = form.cleaned_data
    with transaction.atomic():
        line = order.lines.select_for_update().select_related("rate_card").first()
        new_rate = data.get("applied_rate_per_kg")
        if line and new_rate is not None and new_rate != line.applied_rate_per_kg:
            line.applied_rate_per_kg = new_rate
            line.rate_override_reason = data.get("rate_override_reason", "")
            line.save()
            invoice = revise_invoice_total(invoice, order.total_fee, created_by=request.user, narration="Final rate change at payment")
        forgiven = data.get("forgiven_amount") or Decimal("0.00")
        if forgiven > 0:
            invoice = add_invoice_forgiveness(invoice, forgiven, created_by=request.user)
        current_amount = data.get("current_payment_amount") or Decimal("0.00")
        old_amount = data.get("old_udhaar_payment_amount") or Decimal("0.00")
        total_amount = (current_amount + old_amount).quantize(Decimal("0.01"))
        if total_amount <= 0:
            messages.success(request, "Bill adjustments saved.")
            return redirect("operations:order_detail", pk=pk)
        method = data["payment_method"]
        reference = f"{method}-{uuid.uuid4().hex.upper()}"
        gateway = data.get("provider") if method == "QR" else None
        payment = OrderPayment.objects.create(
            order=order,
            invoice=invoice,
            payment_method=OrderPayment.PaymentMethod.QR if method == "QR" else OrderPayment.PaymentMethod.CASH,
            payment_reference=reference,
            amount=total_amount,
            current_invoice_amount=current_amount,
            old_udhaar_amount=old_amount,
            provider=gateway.name if gateway else "Cash",
            payment_gateway=gateway,
        )
        if method == "CASH":
            settle_order_payment(payment, provider_payload={"source": "cash-counter", "notes": data.get("notes", "")}, created_by=request.user, close_order=False)
            messages.success(request, f"Cash ₹{total_amount:.2f} received and allocated successfully.")
            return redirect("operations:order_detail", pk=pk)
        if not gateway or not gateway.is_ready_for_payment:
            payment.delete()
            messages.error(request, "The selected payment gateway is not ready. Configure its required credentials in Django Admin.")
            return redirect("operations:order_detail", pk=pk)
    return _payment_gateway_response(request, order, payment, gateway)


@module_required("grinding")
@require_POST
def order_buyback(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(GrindingOrder.objects.select_related("customer").prefetch_related("lines"), pk=pk)
    form = OrderBuybackForm(request.POST, order=order)
    if not form.is_valid():
        return render(request, "operations/order_detail.html", _order_payment_context(order, bound_buyback_form=form), status=400)
    try:
        tx = form.save()
        post_buyback(tx, created_by=request.user)
        messages.success(request, f"Buyback {tx.reference} posted: ₹{tx.buyback_value:.2f}. Current adjustment ₹{tx.adjusted_current_amount:.2f}, old udhaar ₹{tx.adjusted_old_amount:.2f}, cash payout ₹{tx.cash_paid_amount:.2f}.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("operations:order_detail", pk=pk)


@module_required("grinding")
@require_POST
def order_status(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(GrindingOrder, pk=pk)
    new_status = request.POST.get("status", "")
    try:
        order = change_order_status(order, new_status, user=request.user)
        messages.success(request, f"Order moved to {order.get_status_display()}.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    if request.headers.get("HX-Request") == "true":
        order.refresh_from_db()
        return render(request, "operations/_order_card.html", {"order": order})
    return redirect("operations:order_detail", pk=pk)


@module_required("grinding")
@require_POST
def request_qr_payment(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(GrindingOrder.objects.select_related("customer"), pk=pk)
    invoice = get_object_or_404(Invoice, order=order)
    form = PaymentRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Select an active payment gateway and enter a valid payment amount.")
        return redirect("operations:order_detail", pk=pk)
    amount = form.cleaned_data["amount"]
    gateway: PaymentGatewayConfig = form.cleaned_data["provider"]
    if amount > invoice.outstanding_amount:
        messages.error(request, "Payment amount cannot exceed the invoice outstanding balance.")
        return redirect("operations:order_detail", pk=pk)
    if not gateway.is_ready_for_payment:
        messages.error(request, "The selected payment gateway is not ready. Configure it in Django Admin.")
        return redirect("operations:order_detail", pk=pk)
    payment = OrderPayment.objects.create(order=order, invoice=invoice, payment_method=OrderPayment.PaymentMethod.QR, payment_reference=f"QR-{uuid.uuid4().hex.upper()}", amount=amount, current_invoice_amount=amount, provider=gateway.name, payment_gateway=gateway)
    return _payment_gateway_response(request, order, payment, gateway)


@module_required("grinding")
def payment_status(request: HttpRequest, reference: str) -> HttpResponse:
    payment = get_object_or_404(OrderPayment.objects.select_related("order", "invoice", "payment_gateway"), payment_reference=reference)
    response = render(request, "operations/_payment_status.html", {"payment": payment})
    if payment.settlement_status == OrderPayment.SettlementStatus.SETTLED:
        response["HX-Trigger"] = json.dumps({"paymentSettled": {"reference": payment.payment_reference, "order": payment.order.order_number}})
    return response


@csrf_exempt
@require_POST
def qr_webhook(request: HttpRequest) -> JsonResponse:
    raw = request.body
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)
    reference = str(payload.get("payment_reference", "")).strip()
    provider_status = str(payload.get("status", "")).upper()
    if not reference or provider_status not in {"SETTLED", "SUCCESS", "PAID"}:
        return JsonResponse({"ok": False, "error": "invalid_payment_state"}, status=400)
    try:
        payment_snapshot = OrderPayment.objects.select_related("payment_gateway").get(payment_reference=reference)
    except OrderPayment.DoesNotExist:
        return JsonResponse({"ok": False, "error": "unknown_payment_reference"}, status=404)
    gateway = payment_snapshot.payment_gateway
    if gateway is None or not gateway.is_active:
        return JsonResponse({"ok": False, "error": "payment_gateway_unavailable"}, status=409)
    if not _verify_gateway_signature(gateway, request, raw):
        return JsonResponse({"ok": False, "error": "invalid_signature"}, status=401)
    try:
        with transaction.atomic():
            payment = OrderPayment.objects.select_for_update().select_related("order", "invoice", "payment_gateway").get(payment_reference=reference)
            if payload.get("amount") is not None:
                incoming = Decimal(str(payload["amount"])).quantize(Decimal("0.01"))
                if incoming != payment.amount:
                    return JsonResponse({"ok": False, "error": "amount_mismatch"}, status=409)
            settle_order_payment(payment, provider_payload=payload, close_order=True)
            payment.refresh_from_db(); payment.order.refresh_from_db()
    except (InvalidOperation, ValidationError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=409)
    response = JsonResponse({"ok": True, "payment_reference": reference, "settlement_status": payment.settlement_status, "order_status": payment.order.status})
    response["HX-Trigger"] = json.dumps({"paymentSettled": {"reference": reference, "order": payment.order.order_number, "label": "Paid & Cleared"}})
    return response


@module_required("rate_card")
def rate_card(request: HttpRequest) -> HttpResponse:
    form = RateCardForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Rate card saved."); return redirect("operations:rate_card")
    return render(request, "operations/rate_card.html", {"rates": RateCard.objects.all(), "form": form})


@module_required("buyback")
def buyback(request: HttpRequest) -> HttpResponse:
    form = BuybackForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(); post_buyback(obj, created_by=request.user); messages.success(request, f"Buyback {obj.reference} posted."); return redirect("operations:buyback")
    buyback_rates = ChakkiSettings.load().buyback_rates or {}
    return render(request, "operations/buyback.html", {"form": form, "transactions": BuybackTransaction.objects.select_related("customer").prefetch_related("lines")[:100], "buyback_rates": buyback_rates})


@module_required("production")
def production(request: HttpRequest) -> HttpResponse:
    form = ProductionLogForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Production mass-balance log saved."); return redirect("operations:production")
    return render(request, "operations/production.html", {"form": form, "logs": ProductionLog.objects.order_by("-production_date")[:100]})


@module_required("wastage")
def wastage(request: HttpRequest) -> HttpResponse:
    form = WastageLogForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Wastage log saved."); return redirect("operations:wastage")
    return render(request, "operations/wastage.html", {"form": form, "logs": WastageLog.objects.order_by("-wastage_date")[:100]})


@module_required("utilities")
def utilities(request: HttpRequest) -> HttpResponse:
    form = UtilityLedgerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(); post_utility_cost(obj, created_by=request.user); messages.success(request, "Utility cost posted."); return redirect("operations:utilities")
    return render(request, "operations/utilities.html", {"form": form, "logs": UtilityLedger.objects.order_by("-period")[:100]})
