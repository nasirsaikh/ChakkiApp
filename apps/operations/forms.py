from decimal import Decimal

from django import forms
from django.db import transaction

from apps.configuration.models import ChakkiSettings, PaymentGatewayConfig
from apps.customers.models import Customer
from apps.inventory.models import InventoryItem
from .models import BuybackLine, BuybackTransaction, GrindingOrder, GrindingOrderLine, ProductionLog, RateCard, UtilityLedger, WastageLog

BASE = "w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50"
CHECK = "h-4 w-4 rounded border border-input text-primary focus:ring-ring"


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = CHECK if isinstance(field.widget, forms.CheckboxInput) else BASE


class RateCardForm(StyledModelForm):
    class Meta:
        model = RateCard
        fields = [
            "grain_type",
            "flour_type",
            "service_name",
            "with_jalan",
            "system_rate_per_kg",
            "allow_override",
            "minimum_rate_per_kg",
            "maximum_rate_per_kg",
            "effective_from",
            "is_active",
        ]
        widgets = {"effective_from": forms.DateInput(attrs={"type": "date"})}


class GrindingIntakeForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True).order_by("name"))
    rate_card = forms.ModelChoiceField(queryset=RateCard.objects.none())
    weight_kg = forms.DecimalField(min_value=Decimal("0.001"), max_digits=10, decimal_places=3)
    applied_rate_per_kg = forms.DecimalField(
        min_value=Decimal("0.00"),
        max_digits=8,
        decimal_places=2,
        required=False,
        help_text="Leave blank to use the system rate.",
    )
    rate_override_reason = forms.CharField(max_length=255, required=False)
    paid_amount = forms.DecimalField(min_value=Decimal("0.00"), max_digits=12, decimal_places=2, initial=0)
    forgiven_amount = forms.DecimalField(min_value=Decimal("0.00"), max_digits=12, decimal_places=2, initial=0)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rate_card"].queryset = RateCard.objects.filter(is_active=True).order_by("grain_type", "flour_type", "with_jalan")
        for field in self.fields.values():
            field.widget.attrs["class"] = BASE

    def clean(self):
        data = super().clean()
        card = data.get("rate_card")
        rate = data.get("applied_rate_per_kg")
        reason = (data.get("rate_override_reason") or "").strip()
        if card:
            if rate is None:
                data["applied_rate_per_kg"] = card.system_rate_per_kg
            elif rate != card.system_rate_per_kg:
                if not card.allow_override:
                    self.add_error("applied_rate_per_kg", "This rate card does not permit overrides.")
                elif not (card.minimum_rate_per_kg <= rate <= card.maximum_rate_per_kg):
                    self.add_error("applied_rate_per_kg", "Rate is outside the configured allowed range.")
                if not reason:
                    self.add_error("rate_override_reason", "Enter a reason for changing the system rate.")
            fee = (data.get("weight_kg") or 0) * (data.get("applied_rate_per_kg") or 0)
            if (data.get("paid_amount") or 0) + (data.get("forgiven_amount") or 0) > fee:
                raise forms.ValidationError("Paid plus forgiven cannot exceed the grinding fee.")
        return data

    @transaction.atomic
    def save(self, user):
        data = self.cleaned_data
        card = data["rate_card"]
        order = GrindingOrder.objects.create(customer=data["customer"], notes=data["notes"], created_by=user)
        GrindingOrderLine.objects.create(
            order=order,
            rate_card=card,
            grain_type=card.grain_type,
            flour_type=card.flour_type,
            weight_kg=data["weight_kg"],
            with_jalan=card.with_jalan,
            system_rate_per_kg=card.system_rate_per_kg,
            applied_rate_per_kg=data["applied_rate_per_kg"],
            rate_override_reason=data["rate_override_reason"],
        )
        return order


class PaymentRequestForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    provider = forms.ModelChoiceField(
        queryset=PaymentGatewayConfig.objects.none(),
        empty_label=None,
        label="UPI / payment gateway",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        gateways = PaymentGatewayConfig.objects.filter(is_active=True).order_by("-is_default", "name")
        self.fields["provider"].queryset = gateways
        default = gateways.filter(is_default=True).first() or gateways.first()
        if default and not self.is_bound:
            self.fields["provider"].initial = default.pk
        for field in self.fields.values():
            field.widget.attrs["class"] = BASE


class BuybackForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True))
    order = forms.ModelChoiceField(queryset=GrindingOrder.objects.all(), required=False)
    processing_fee = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, initial=0)
    product_type = forms.ChoiceField(choices=BuybackLine.ProductType.choices)
    inventory_item = forms.ModelChoiceField(queryset=InventoryItem.objects.filter(is_active=True).order_by("name"))
    quantity_kg = forms.DecimalField(min_value=Decimal("0.001"), max_digits=10, decimal_places=3)
    system_rate_per_kg = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False)
    applied_rate_per_kg = forms.DecimalField(
        min_value=0,
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="Leave blank to use the system buyback rate.",
    )
    override_reason = forms.CharField(required=False)
    notes = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = BASE

    def clean(self):
        data = super().clean()
        product = data.get("product_type")
        configured = ChakkiSettings.load().buyback_rates or {}
        if product:
            try:
                system_rate = Decimal(str(configured.get(product, "0"))).quantize(Decimal("0.01"))
            except Exception:
                system_rate = Decimal("0.00")
            if system_rate <= 0:
                self.add_error("product_type", "Configure a positive system buyback rate for this product in Django Admin.")
            data["system_rate_per_kg"] = system_rate
            applied = data.get("applied_rate_per_kg")
            if applied is None:
                data["applied_rate_per_kg"] = system_rate
            elif applied != system_rate and not (data.get("override_reason") or "").strip():
                self.add_error("override_reason", "Reason required for a buyback rate override.")
        return data

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        tx = BuybackTransaction.objects.create(
            customer=data["customer"],
            order=data["order"],
            processing_fee=data["processing_fee"],
            notes=data["notes"],
        )
        BuybackLine.objects.create(
            transaction=tx,
            inventory_item=data["inventory_item"],
            product_type=data["product_type"],
            quantity_kg=data["quantity_kg"],
            system_rate_per_kg=data["system_rate_per_kg"],
            applied_rate_per_kg=data["applied_rate_per_kg"],
            override_reason=data["override_reason"],
        )
        tx.recalculate()
        tx.save(update_fields=["buyback_value", "net_customer_payable", "updated_at"])
        return tx


class ProductionLogForm(StyledModelForm):
    class Meta:
        model = ProductionLog
        fields = ["production_date", "product_name", "input_weight_kg", "output_weight_kg", "byproduct_weight_kg", "process_loss_kg", "notes"]
        widgets = {"production_date": forms.DateInput(attrs={"type": "date"})}


class WastageLogForm(StyledModelForm):
    class Meta:
        model = WastageLog
        fields = ["wastage_date", "process", "input_weight_kg", "milling_loss_kg", "dust_kg", "other_waste_kg", "reason"]
        widgets = {"wastage_date": forms.DateInput(attrs={"type": "date"})}


class UtilityLedgerForm(StyledModelForm):
    class Meta:
        model = UtilityLedger
        fields = ["period", "utility_type", "units", "unit_label", "amount", "reference", "notes"]
        widgets = {"period": forms.DateInput(attrs={"type": "date"})}
