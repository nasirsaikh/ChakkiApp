from __future__ import annotations

import json
from decimal import Decimal

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.configuration.models import PaymentGatewayConfig
from .models import OrderPayment
from .payment_gateways.razorpay import fetch_payment, verify_payment_signature, verify_webhook_signature
from .payment_services import settle_gateway_payment


def _amount_in_paise(amount: Decimal) -> int:
    return int((Decimal(str(amount)) * Decimal("100")).quantize(Decimal("1")))


def _find_payment_by_razorpay_order(order_id: str) -> OrderPayment | None:
    if not order_id:
        return None
    return (
        OrderPayment.objects.select_related("order", "invoice", "payment_gateway")
        .filter(
            payment_gateway__provider=PaymentGatewayConfig.Provider.RAZORPAY,
            provider_payload__razorpay_order__id=order_id,
        )
        .first()
    )


@require_POST
def razorpay_verify(request: HttpRequest) -> JsonResponse:
    reference = (request.POST.get("payment_reference") or "").strip()
    razorpay_order_id = (request.POST.get("razorpay_order_id") or "").strip()
    razorpay_payment_id = (request.POST.get("razorpay_payment_id") or "").strip()
    razorpay_signature = (request.POST.get("razorpay_signature") or "").strip()
    if not all([reference, razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        return JsonResponse({"ok": False, "error": "Missing Razorpay verification data."}, status=400)

    try:
        payment = OrderPayment.objects.select_related("order", "invoice", "payment_gateway").get(payment_reference=reference)
    except OrderPayment.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Unknown payment reference."}, status=404)

    gateway = payment.payment_gateway
    if not gateway or gateway.provider != PaymentGatewayConfig.Provider.RAZORPAY or not gateway.is_ready_for_payment:
        return JsonResponse({"ok": False, "error": "Razorpay gateway is unavailable."}, status=409)

    stored_order = (payment.provider_payload or {}).get("razorpay_order") or {}
    if stored_order.get("id") != razorpay_order_id:
        return JsonResponse({"ok": False, "error": "Razorpay order mismatch."}, status=409)

    try:
        verify_payment_signature(
            gateway,
            order_id=razorpay_order_id,
            payment_id=razorpay_payment_id,
            signature=razorpay_signature,
        )
        provider_payment = fetch_payment(gateway, razorpay_payment_id)
    except Exception:
        return JsonResponse({"ok": False, "error": "Razorpay payment signature verification failed."}, status=400)

    if provider_payment.get("order_id") != razorpay_order_id:
        return JsonResponse({"ok": False, "error": "Provider order mismatch."}, status=409)
    if int(provider_payment.get("amount") or 0) != _amount_in_paise(payment.amount):
        return JsonResponse({"ok": False, "error": "Provider amount mismatch."}, status=409)

    payload = dict(payment.provider_payload or {})
    payload["razorpay_payment"] = provider_payment
    payload["razorpay_payment_id"] = razorpay_payment_id
    payload["razorpay_signature_verified"] = True

    if provider_payment.get("status") != "captured" and not provider_payment.get("captured"):
        payment.provider_payload = payload
        payment.save(update_fields=["provider_payload", "updated_at"])
        return JsonResponse({"ok": True, "pending": True, "message": "Payment is verified and awaiting capture."}, status=202)

    try:
        with transaction.atomic():
            settle_gateway_payment(payment, provider_payload=payload, created_by=request.user if request.user.is_authenticated else None, close_order=True)
    except Exception:
        return JsonResponse({"ok": False, "error": "Payment was verified but settlement could not be posted."}, status=409)

    return JsonResponse({"ok": True, "settled": True, "payment_reference": payment.payment_reference})


@csrf_exempt
@require_POST
def razorpay_webhook(request: HttpRequest) -> JsonResponse:
    raw = request.body
    signature = (request.headers.get("X-Razorpay-Signature") or "").strip()
    if not signature:
        return JsonResponse({"ok": False, "error": "missing_signature"}, status=401)

    gateway = None
    for candidate in PaymentGatewayConfig.objects.filter(provider=PaymentGatewayConfig.Provider.RAZORPAY, is_active=True):
        try:
            verify_webhook_signature(candidate, raw_body=raw, signature=signature)
            gateway = candidate
            break
        except Exception:
            continue
    if gateway is None:
        return JsonResponse({"ok": False, "error": "invalid_signature"}, status=401)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    event = str(payload.get("event") or "")
    payment_entity = (((payload.get("payload") or {}).get("payment") or {}).get("entity") or {})
    order_entity = (((payload.get("payload") or {}).get("order") or {}).get("entity") or {})
    order_id = str(payment_entity.get("order_id") or order_entity.get("id") or "")
    payment = _find_payment_by_razorpay_order(order_id)
    if payment is None:
        return JsonResponse({"ok": True, "ignored": "unknown_order"})
    if payment.payment_gateway_id != gateway.pk:
        return JsonResponse({"ok": False, "error": "gateway_mismatch"}, status=409)

    if event == "payment.failed":
        if payment.settlement_status != OrderPayment.SettlementStatus.SETTLED:
            merged = dict(payment.provider_payload or {})
            merged["last_webhook"] = payload
            payment.settlement_status = OrderPayment.SettlementStatus.FAILED
            payment.provider_payload = merged
            payment.save(update_fields=["settlement_status", "provider_payload", "updated_at"])
        return JsonResponse({"ok": True, "status": payment.settlement_status})

    if event not in {"payment.captured", "order.paid"}:
        return JsonResponse({"ok": True, "ignored": event})

    if payment_entity:
        if int(payment_entity.get("amount") or 0) != _amount_in_paise(payment.amount):
            return JsonResponse({"ok": False, "error": "amount_mismatch"}, status=409)
        if payment_entity.get("status") not in {"captured", None} and not payment_entity.get("captured"):
            return JsonResponse({"ok": True, "ignored": "not_captured"})

    merged = dict(payment.provider_payload or {})
    merged["last_webhook"] = payload
    if payment_entity:
        merged["razorpay_payment"] = payment_entity
        merged["razorpay_payment_id"] = payment_entity.get("id")

    try:
        settle_gateway_payment(payment, provider_payload=merged, close_order=True)
    except Exception:
        return JsonResponse({"ok": False, "error": "settlement_failed"}, status=409)
    return JsonResponse({"ok": True, "status": "SETTLED", "payment_reference": payment.payment_reference})
