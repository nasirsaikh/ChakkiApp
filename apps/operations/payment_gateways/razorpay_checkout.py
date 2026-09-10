from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.configuration.models import ChakkiSettings, PaymentGatewayConfig
from apps.operations.models import GrindingOrder, OrderPayment
from .razorpay import create_order


def render_razorpay_checkout(
    request: HttpRequest,
    order: GrindingOrder,
    payment: OrderPayment,
    gateway: PaymentGatewayConfig,
) -> HttpResponse:
    razorpay_order = create_order(gateway, payment)
    payload = dict(payment.provider_payload or {})
    payload["razorpay_order"] = razorpay_order
    payment.provider_payload = payload
    payment.save(update_fields=["provider_payload", "updated_at"])
    chakki = ChakkiSettings.load()
    return render(
        request,
        "operations/payment_razorpay.html",
        {
            "payment": payment,
            "order": order,
            "gateway": gateway,
            "razorpay_order": razorpay_order,
            "merchant_name": gateway.merchant_name or chakki.brand_name,
        },
    )
