from __future__ import annotations

from decimal import Decimal

import razorpay
from django.core.exceptions import ImproperlyConfigured

from apps.configuration.models import PaymentGatewayConfig


def get_client(gateway: PaymentGatewayConfig) -> razorpay.Client:
    if gateway.provider != PaymentGatewayConfig.Provider.RAZORPAY:
        raise ImproperlyConfigured("The selected gateway is not Razorpay.")
    if not gateway.key_id or not gateway.has_key_secret:
        raise ImproperlyConfigured("Razorpay API credentials are not configured.")
    return razorpay.Client(auth=(gateway.key_id, gateway.key_secret))


def create_order(gateway: PaymentGatewayConfig, payment) -> dict:
    client = get_client(gateway)
    amount_paise = int((Decimal(str(payment.amount)) * Decimal("100")).quantize(Decimal("1")))
    if amount_paise <= 0:
        raise ValueError("Razorpay payment amount must be greater than zero.")
    return client.order.create(
        data={
            "amount": amount_paise,
            "currency": gateway.currency_code or "INR",
            "receipt": payment.payment_reference,
            "notes": {
                "chakki_payment_id": str(payment.pk),
                "payment_reference": payment.payment_reference,
                "invoice_id": str(payment.invoice_id),
                "grinding_order_id": str(payment.order_id),
            },
        }
    )


def verify_payment_signature(gateway: PaymentGatewayConfig, *, order_id: str, payment_id: str, signature: str) -> None:
    client = get_client(gateway)
    client.utility.verify_payment_signature(
        {
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        }
    )


def verify_webhook_signature(gateway: PaymentGatewayConfig, *, raw_body: bytes, signature: str) -> None:
    if not gateway.has_webhook_secret:
        raise ImproperlyConfigured("Razorpay webhook secret is not configured.")
    client = get_client(gateway)
    client.utility.verify_webhook_signature(raw_body.decode("utf-8"), signature, gateway.webhook_secret)


def fetch_payment(gateway: PaymentGatewayConfig, payment_id: str) -> dict:
    return get_client(gateway).payment.fetch(payment_id)
