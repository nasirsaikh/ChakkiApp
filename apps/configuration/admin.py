from __future__ import annotations

from django import forms
from django.contrib import admin

from .models import ChakkiSettings, PaymentGatewayConfig


@admin.register(ChakkiSettings)
class ChakkiSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Brand", {"fields": ("brand_name", "owner_name", "phone", "address", "village")}),
        (
            "System",
            {
                "fields": (
                    "currency_code",
                    "currency_symbol",
                    "default_language",
                    "default_grinding_rate",
                    "buyback_rates",
                    "invoice_footer",
                )
            },
        ),
    )

    def has_add_permission(self, request) -> bool:
        return not ChakkiSettings.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class PaymentGatewayConfigAdminForm(forms.ModelForm):
    key_secret = forms.CharField(
        required=False,
        label="API key secret",
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Leave blank to preserve the currently stored encrypted secret.",
    )
    webhook_secret = forms.CharField(
        required=False,
        label="Webhook signing secret",
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Required before a gateway can be activated. Stored encrypted in the database.",
    )

    class Meta:
        model = PaymentGatewayConfig
        fields = (
            "name",
            "provider",
            "is_active",
            "is_default",
            "upi_vpa",
            "merchant_name",
            "merchant_id",
            "key_id",
            "key_secret",
            "webhook_secret",
            "webhook_signature_header",
            "signature_algorithm",
            "currency_code",
            "provider_base_url",
            "metadata",
        )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_active"):
            existing_secret = bool(self.instance and self.instance.pk and self.instance.webhook_secret_encrypted)
            if not (cleaned.get("webhook_secret") or existing_secret):
                self.add_error("webhook_secret", "Enter a webhook signing secret before activating this gateway.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        key_secret = self.cleaned_data.get("key_secret") or ""
        webhook_secret = self.cleaned_data.get("webhook_secret") or ""
        if key_secret:
            obj.set_key_secret(key_secret)
        if webhook_secret:
            obj.set_webhook_secret(webhook_secret)
        if commit:
            obj.save()
        return obj


@admin.register(PaymentGatewayConfig)
class PaymentGatewayConfigAdmin(admin.ModelAdmin):
    form = PaymentGatewayConfigAdminForm
    list_display = ("name", "provider", "upi_vpa", "is_active", "is_default", "webhook_secret_configured", "updated_at")
    list_filter = ("provider", "is_active", "is_default")
    search_fields = ("name", "upi_vpa", "merchant_id", "key_id")
    readonly_fields = ("webhook_endpoint", "stored_secret_state", "created_at", "updated_at")
    fieldsets = (
        (
            "Gateway",
            {
                "fields": (
                    "name",
                    "provider",
                    "is_active",
                    "is_default",
                    "upi_vpa",
                    "merchant_name",
                    "currency_code",
                )
            },
        ),
        (
            "Provider credentials",
            {"fields": ("merchant_id", "key_id", "key_secret", "provider_base_url", "metadata")},
        ),
        (
            "Webhook verification",
            {
                "fields": (
                    "webhook_endpoint",
                    "webhook_signature_header",
                    "signature_algorithm",
                    "webhook_secret",
                    "stored_secret_state",
                )
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Webhook endpoint")
    def webhook_endpoint(self, obj=None) -> str:
        return "/api/v1/payments/qr-webhook/"

    @admin.display(description="Stored credentials")
    def stored_secret_state(self, obj: PaymentGatewayConfig | None) -> str:
        if not obj or not obj.pk:
            return "No credentials stored yet."
        return f"API secret: {'configured' if obj.has_key_secret else 'not configured'}; webhook secret: {'configured' if obj.has_webhook_secret else 'not configured'}"

    @admin.display(boolean=True, description="Webhook secret")
    def webhook_secret_configured(self, obj: PaymentGatewayConfig) -> bool:
        return obj.has_webhook_secret
