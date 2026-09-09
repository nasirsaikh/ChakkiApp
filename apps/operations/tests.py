import hashlib
import hmac
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.configuration.models import PaymentGatewayConfig
from apps.customers.models import Customer
from .models import GrindingOrder, GrindingOrderLine, OrderPayment, RateCard
from .services import finalize_invoice


class PaymentWebhookTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="operator", password="x")
        group = Group.objects.create(name="Operator")
        self.user.groups.add(group)
        self.customer = Customer.objects.create(name="QR Customer")
        self.gateway = PaymentGatewayConfig(
            name="Test UPI",
            provider=PaymentGatewayConfig.Provider.UPI,
            is_active=True,
            is_default=True,
            upi_vpa="test@upi",
            merchant_name="Test Chakki",
            webhook_signature_header="X-Chakki-Signature",
        )
        self.gateway.set_webhook_secret("test-secret")
        self.gateway.save()
        rate = RateCard.objects.create(
            grain_type=RateCard.GrainType.WHEAT,
            flour_type=RateCard.FlourType.ATTA,
            system_rate_per_kg=Decimal("2.00"),
            minimum_rate_per_kg=Decimal("2.00"),
            maximum_rate_per_kg=Decimal("3.00"),
        )
        self.order = GrindingOrder.objects.create(customer=self.customer, status=GrindingOrder.Status.READY)
        GrindingOrderLine.objects.create(
            order=self.order,
            rate_card=rate,
            grain_type=rate.grain_type,
            flour_type=rate.flour_type,
            weight_kg=Decimal("20"),
            with_jalan=False,
            system_rate_per_kg=Decimal("2.00"),
            applied_rate_per_kg=Decimal("2.00"),
        )
        self.invoice = finalize_invoice(self.order)
        self.payment = OrderPayment.objects.create(
            order=self.order,
            invoice=self.invoice,
            payment_reference="QR-TEST-1",
            amount=Decimal("40.00"),
            payment_method=OrderPayment.PaymentMethod.QR,
            provider=self.gateway.name,
            payment_gateway=self.gateway,
        )

    def test_signed_webhook_settles_payment_and_closes_order(self):
        body = json.dumps(
            {"payment_reference": "QR-TEST-1", "status": "SUCCESS", "amount": "40.00"},
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        response = self.client.post(
            reverse("qr_payment_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_CHAKKI_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.invoice.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.settlement_status, OrderPayment.SettlementStatus.SETTLED)
        self.assertEqual(self.invoice.outstanding_amount, Decimal("0.00"))
        self.assertEqual(self.order.payment_status, GrindingOrder.PaymentStatus.PAID)
        self.assertEqual(self.order.status, GrindingOrder.Status.DELIVERED)
        self.assertIn("HX-Trigger", response)

    def test_invalid_signature_is_rejected(self):
        body = json.dumps(
            {"payment_reference": "QR-TEST-1", "status": "SUCCESS", "amount": "40.00"},
            separators=(",", ":"),
        ).encode()
        response = self.client.post(
            reverse("qr_payment_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_CHAKKI_SIGNATURE="bad",
        )
        self.assertEqual(response.status_code, 401)

    def test_amount_mismatch_is_rejected_without_settlement(self):
        body = json.dumps(
            {"payment_reference": "QR-TEST-1", "status": "SUCCESS", "amount": "39.00"},
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        response = self.client.post(
            reverse("qr_payment_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_CHAKKI_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 409)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.settlement_status, OrderPayment.SettlementStatus.PENDING)
