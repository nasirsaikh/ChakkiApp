from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.core.models import TimeStampedModel
from .crypto import decrypt_secret, encrypt_secret


class ChakkiSettings(TimeStampedModel):
    brand_name = models.CharField(max_length=120, default="Chakki ERP", verbose_name="Chakki brand name")
    owner_name = models.CharField(max_length=120, blank=True, verbose_name="Owner name")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Phone")
    address = models.TextField(blank=True, verbose_name="Address")
    village = models.CharField(max_length=120, blank=True, verbose_name="Village / locality")
    currency_code = models.CharField(max_length=8, default="INR", verbose_name="Currency code")
    currency_symbol = models.CharField(max_length=8, default="₹", verbose_name="Currency symbol")
    default_language = models.CharField(
        max_length=5,
        choices=[("en", "English"), ("hi", "हिन्दी")],
        default="en",
        verbose_name="Default language",
    )
    default_grinding_rate = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("2.00"),
        verbose_name="Default grinding rate per kg",
    )
    buyback_rates = models.JSONField(default=dict, blank=True, verbose_name="Default buyback rates")
    invoice_footer = models.CharField(max_length=255, blank=True, verbose_name="Invoice footer")

    class Meta:
        verbose_name = "Chakki settings"
        verbose_name_plural = "Chakki settings"

    def save(self, *args, **kwargs) -> None:
        if not self.pk and ChakkiSettings.objects.exists():
            raise ValidationError("Only one Chakki settings record is allowed.")
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "ChakkiSettings":
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={"buyback_rates": {"KHAL": "20.00", "ATTA": "25.00", "OIL": "120.00", "BRAN": "15.00"}},
        )
        return obj

    def __str__(self) -> str:
        return self.brand_name


class PaymentGatewayConfig(TimeStampedModel):
    class Provider(models.TextChoices):
        UPI = "UPI", "UPI / Bank Dynamic QR"
        RAZORPAY = "RAZORPAY", "Razorpay"
        BHARATPE = "BHARATPE", "BharatPe"
        CUSTOM = "CUSTOM", "Custom Bank / UPI Provider"

    class Environment(models.TextChoices):
        TEST = "TEST", "Test"
        LIVE = "LIVE", "Live"

    class SignatureAlgorithm(models.TextChoices):
        HMAC_SHA256 = "HMAC_SHA256", "HMAC SHA-256 (hex digest)"

    name = models.CharField(max_length=80, unique=True, verbose_name="Configuration name")
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.UPI, verbose_name="Provider")
    environment = models.CharField(max_length=10, choices=Environment.choices, default=Environment.TEST, verbose_name="Environment")
    is_active = models.BooleanField(default=False, db_index=True, verbose_name="Active")
    is_default = models.BooleanField(default=False, verbose_name="Default gateway")
    upi_vpa = models.CharField(max_length=120, blank=True, verbose_name="UPI VPA / merchant address")
    merchant_name = models.CharField(max_length=120, blank=True, verbose_name="Merchant display name")
    merchant_id = models.CharField(max_length=120, blank=True, verbose_name="Merchant ID")
    key_id = models.CharField(max_length=180, blank=True, verbose_name="API key / key ID")
    key_secret_encrypted = models.TextField(blank=True, editable=False)
    webhook_secret_encrypted = models.TextField(blank=True, editable=False)
    webhook_signature_header = models.CharField(
        max_length=80,
        default="X-Chakki-Signature",
        verbose_name="Webhook signature header",
        help_text="Examples: X-Chakki-Signature or X-Razorpay-Signature.",
    )
    signature_algorithm = models.CharField(
        max_length=24,
        choices=SignatureAlgorithm.choices,
        default=SignatureAlgorithm.HMAC_SHA256,
        verbose_name="Webhook signature algorithm",
    )
    currency_code = models.CharField(max_length=8, default="INR", verbose_name="Currency")
    provider_base_url = models.URLField(blank=True, verbose_name="Provider API base URL")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="Provider metadata")

    class Meta:
        ordering = ["-is_default", "name"]
        verbose_name = "Payment / UPI gateway"
        verbose_name_plural = "Payment / UPI gateways"
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="single_default_payment_gateway",
            )
        ]

    def clean(self) -> None:
        if self.is_default and not self.is_active:
            raise ValidationError({"is_default": "The default payment gateway must also be active."})

        if self.provider == self.Provider.RAZORPAY:
            if self.is_active and not self.key_id.strip():
                raise ValidationError({"key_id": "Razorpay Key ID is required for an active Razorpay gateway."})
            if self.key_id:
                expected_prefix = "rzp_test_" if self.environment == self.Environment.TEST else "rzp_live_"
                if not self.key_id.startswith(expected_prefix):
                    raise ValidationError({"key_id": f"{self.get_environment_display()} mode requires a Key ID beginning with {expected_prefix}."})
        elif self.is_active and not self.upi_vpa.strip():
            raise ValidationError({"upi_vpa": "An active direct UPI / QR gateway requires a UPI VPA."})

    @property
    def key_secret(self) -> str:
        return decrypt_secret(self.key_secret_encrypted)

    @property
    def webhook_secret(self) -> str:
        return decrypt_secret(self.webhook_secret_encrypted)

    @property
    def has_key_secret(self) -> bool:
        return bool(self.key_secret_encrypted)

    @property
    def has_webhook_secret(self) -> bool:
        return bool(self.webhook_secret_encrypted)

    @property
    def is_ready_for_payment(self) -> bool:
        if not self.is_active or not self.has_webhook_secret:
            return False
        if self.provider == self.Provider.RAZORPAY:
            return bool(self.key_id.strip() and self.has_key_secret)
        return bool(self.upi_vpa.strip())

    def set_key_secret(self, value: str) -> None:
        self.key_secret_encrypted = encrypt_secret(value)

    def set_webhook_secret(self, value: str) -> None:
        self.webhook_secret_encrypted = encrypt_secret(value)

    def save(self, *args, **kwargs) -> None:
        if self.is_active and not self.has_webhook_secret:
            raise ValidationError("An active gateway requires a webhook secret. Enter it in Django Admin.")
        if self.is_active and self.provider == self.Provider.RAZORPAY and not self.has_key_secret:
            raise ValidationError("An active Razorpay gateway requires an API Key Secret. Enter it in Django Admin.")
        with transaction.atomic():
            if self.is_default:
                PaymentGatewayConfig.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
            self.full_clean()
            super().save(*args, **kwargs)

    @classmethod
    def default_active(cls) -> "PaymentGatewayConfig | None":
        return cls.objects.filter(is_active=True).order_by("-is_default", "name").first()

    def __str__(self) -> str:
        state = "active" if self.is_active else "disabled"
        return f"{self.name} ({self.get_provider_display()}, {self.get_environment_display()}, {state})"
