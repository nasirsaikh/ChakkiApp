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
        min_value=Decimal("0.00"), max_digits=8, decimal_places=2, required=False,
        help_text="Leave blank to use the system rate.",
    )
    rate_override_reason = forms.CharField(max_length=255, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, order: GrindingOrder | None = None, **kwargs):
        self.order = order
        super().__init__(*args, **kwargs)
        self.fields["rate_card"].queryset = RateCard.objects.filter(is_active=True).order_by("grain_type", "flour_type", "with_jalan")
        if order is not None and not self.is_bound:
            line = order.lines.select_related("rate_card").first()
            self.initial.update({"customer": order.customer_id, "notes": order.notes})
            if line:
                self.initial.update({
                    "rate_card": line.rate_card_id,
                    "weight_kg": line.weight_kg,
                    "applied_rate_per_kg": line.applied_rate_per_kg,
                    "rate_override_reason": line.rate_override_reason,
                })
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
        return data

    @transaction.atomic
    def save(self, user):
        data = self.cleaned_data
        card = data["rate_card"]
        if self.order is None:
            order = GrindingOrder.objects.create(customer=data["customer"], notes=data["notes"], created_by=user)
            line = GrindingOrderLine(order=order)
        else:
            order = GrindingOrder.objects.select_for_update().get(pk=self.order.pk)
            order.customer = data["customer"]
            order.notes = data["notes"]
            order.save(update_fields=["customer", "notes", "updated_at"])
            line = order.lines.select_for_update().first() or GrindingOrderLine(order=order)
        line.rate_card = card
        line.grain_type = card.grain_type
        line.flour_type = card.flour_type
        line.weight_kg = data["weight_kg"]
        line.with_jalan = card.with_jalan
        line.system_rate_per_kg = card.system_rate_per_kg
        line.applied_rate_per_kg = data["applied_rate_per_kg"]
        line.rate_override_reason = data["rate_override_reason"]
        line.save()
        return order


class BillSettlementForm(forms.Form):
    PAYMENT_CHOICES = (("CASH", "Cash"), ("QR", "UPI / Dynamic QR"))
    payment_method = forms.ChoiceField(choices=PAYMENT_CHOICES, initial="CASH")
    current_payment_amount = forms.DecimalField(min_value=Decimal("0.00"), max_digits=12, decimal_places=2, initial=0, label="Pay current grinding / udhaar")
    old_udhaar_payment_amount = forms.DecimalField(min_value=Decimal("0.00"), max_digits=12, decimal_places=2, initial=0, label="Adjust old udhaar")
    forgiven_amount = forms.DecimalField(min_value=Decimal("0.00"), max_digits=12, decimal_places=2, initial=0, label="Forgiven / goodwill")
    applied_rate_per_kg = forms.DecimalField(min_value=Decimal("0.00"), max_digits=8, decimal_places=2, required=False, label="Final grinding rate / kg")
    rate_override_reason = forms.CharField(max_length=255, required=False, label="Rate change reason")
    provider = forms.ModelChoiceField(queryset=PaymentGatewayConfig.objects.none(), required=False, label="UPI / payment gateway")
    notes = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, order: GrindingOrder, invoice, old_udhaar_total: Decimal = Decimal("0.00"), **kwargs):
        self.order = order
        self.invoice = invoice
        self.old_udhaar_total = Decimal(str(old_udhaar_total or 0))
        super().__init__(*args, **kwargs)
        gateways = PaymentGatewayConfig.objects.filter(is_active=True).order_by("-is_default", "name")
        self.fields["provider"].queryset = gateways
        default = gateways.filter(is_default=True).first() or gateways.first()
        line = order.lines.select_related("rate_card").first()
        if not self.is_bound:
            self.initial["current_payment_amount"] = invoice.outstanding_amount
            if line:
                self.initial["applied_rate_per_kg"] = line.applied_rate_per_kg
            if default:
                self.initial["provider"] = default.pk
        for field in self.fields.values():
            field.widget.attrs["class"] = BASE

    def clean(self):
        data = super().clean()
        current = data.get("current_payment_amount") or Decimal("0.00")
        old = data.get("old_udhaar_payment_amount") or Decimal("0.00")
        forgiven = data.get("forgiven_amount") or Decimal("0.00")
        method = data.get("payment_method")
        line = self.order.lines.select_related("rate_card").first()
        prospective_total = self.invoice.total_grinding_fee
        if line and data.get("applied_rate_per_kg") is not None:
            rate = data["applied_rate_per_kg"]
            card = line.rate_card
            if rate != line.applied_rate_per_kg:
                if not card.allow_override:
                    self.add_error("applied_rate_per_kg", "This rate cannot be changed.")
                elif not (card.minimum_rate_per_kg <= rate <= card.maximum_rate_per_kg):
                    self.add_error("applied_rate_per_kg", "Rate is outside the configured allowed range.")
                if not (data.get("rate_override_reason") or "").strip():
                    self.add_error("rate_override_reason", "Enter a reason for the rate change.")
            prospective_total = (line.weight_kg * rate).quantize(Decimal("0.01"))
        prospective_outstanding = prospective_total - self.invoice.paid_amount - self.invoice.forgiven_amount
        if prospective_outstanding < 0:
            self.add_error("applied_rate_per_kg", "The revised grinding fee cannot be lower than amounts already paid/forgiven.")
        if current + forgiven > prospective_outstanding:
            raise forms.ValidationError("Current payment plus new forgiveness cannot exceed the revised current outstanding amount.")
        if old > self.old_udhaar_total:
            self.add_error("old_udhaar_payment_amount", "Old udhaar adjustment cannot exceed the old outstanding balance.")
        if method == "QR" and not data.get("provider"):
            self.add_error("provider", "Select an active UPI gateway for QR payment.")
        if current + old <= 0 and forgiven <= 0 and (not line or data.get("applied_rate_per_kg") == line.applied_rate_per_kg):
            raise forms.ValidationError("Enter a payment, forgiveness, or rate change to continue.")
        return data


class PaymentRequestForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), max_digits=12, decimal_places=2)
    provider = forms.ModelChoiceField(queryset=PaymentGatewayConfig.objects.none(), empty_label=None, label="UPI / payment gateway")

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
    applied_rate_per_kg = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False, help_text="Leave blank to use the system buyback rate.")
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
        tx = BuybackTransaction.objects.create(customer=data["customer"], order=data["order"], processing_fee=data["processing_fee"], notes=data["notes"])
        BuybackLine.objects.create(transaction=tx, inventory_item=data["inventory_item"], product_type=data["product_type"], quantity_kg=data["quantity_kg"], system_rate_per_kg=data["system_rate_per_kg"], applied_rate_per_kg=data["applied_rate_per_kg"], override_reason=data["override_reason"])
        tx.recalculate(); tx.save(update_fields=["buyback_value", "net_customer_payable", "updated_at"])
        return tx


class OrderBuybackForm(forms.Form):
    adjustment_target = forms.ChoiceField(choices=BuybackTransaction.AdjustmentTarget.choices, initial=BuybackTransaction.AdjustmentTarget.AUTO, label="Adjust buyback against")
    atta_inventory_item = forms.ModelChoiceField(queryset=InventoryItem.objects.none(), required=False, label="Atta inventory item")
    atta_quantity_kg = forms.DecimalField(min_value=Decimal("0.001"), max_digits=10, decimal_places=3, required=False, label="Atta buyback kg")
    atta_rate_per_kg = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False, label="Atta buyback rate / kg")
    atta_override_reason = forms.CharField(max_length=255, required=False, label="Atta rate change reason")
    khal_inventory_item = forms.ModelChoiceField(queryset=InventoryItem.objects.none(), required=False, label="Khal inventory item")
    khal_quantity_kg = forms.DecimalField(min_value=Decimal("0.001"), max_digits=10, decimal_places=3, required=False, label="Khal buyback kg")
    khal_rate_per_kg = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, required=False, label="Khal buyback rate / kg")
    khal_override_reason = forms.CharField(max_length=255, required=False, label="Khal rate change reason")
    notes = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, order: GrindingOrder, **kwargs):
        self.order = order
        super().__init__(*args, **kwargs)
        self.has_atta = order.lines.filter(grain_type=RateCard.GrainType.WHEAT).exists()
        self.has_khal = order.lines.filter(flour_type=RateCard.FlourType.OIL).exists() or order.lines.filter(grain_type=RateCard.GrainType.MUSTARD).exists()
        atta_items = InventoryItem.objects.filter(is_active=True, category=InventoryItem.Category.FINISHED).order_by("name")
        khal_items = InventoryItem.objects.filter(is_active=True, category=InventoryItem.Category.BYPRODUCT).order_by("name")
        self.fields["atta_inventory_item"].queryset = atta_items
        self.fields["khal_inventory_item"].queryset = khal_items
        rates = ChakkiSettings.load().buyback_rates or {}
        self.atta_system_rate = Decimal(str(rates.get("ATTA", "0") or "0")).quantize(Decimal("0.01"))
        self.khal_system_rate = Decimal(str(rates.get("KHAL", "0") or "0")).quantize(Decimal("0.01"))
        if not self.is_bound:
            if self.has_atta:
                self.initial.update({"atta_inventory_item": atta_items.first(), "atta_rate_per_kg": self.atta_system_rate})
            if self.has_khal:
                self.initial.update({"khal_inventory_item": khal_items.first(), "khal_rate_per_kg": self.khal_system_rate})
        for field in self.fields.values():
            field.widget.attrs["class"] = BASE

    def clean(self):
        data = super().clean()
        any_line = False
        for prefix, enabled, system_rate in (("atta", self.has_atta, self.atta_system_rate), ("khal", self.has_khal, self.khal_system_rate)):
            qty = data.get(f"{prefix}_quantity_kg")
            if qty:
                any_line = True
                if not enabled:
                    self.add_error(f"{prefix}_quantity_kg", f"{prefix.title()} buyback is not applicable to this grinding order.")
                if not data.get(f"{prefix}_inventory_item"):
                    self.add_error(f"{prefix}_inventory_item", "Select the inventory item.")
                rate = data.get(f"{prefix}_rate_per_kg")
                if rate is None or rate <= 0:
                    self.add_error(f"{prefix}_rate_per_kg", "Enter a positive buyback rate.")
                elif system_rate > 0 and rate != system_rate and not (data.get(f"{prefix}_override_reason") or "").strip():
                    self.add_error(f"{prefix}_override_reason", "Enter a reason for changing the system buyback rate.")
        if not any_line:
            raise forms.ValidationError("Enter Atta and/or Khal quantity to buy back.")
        return data

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        tx = BuybackTransaction.objects.create(customer=self.order.customer, order=self.order, processing_fee=Decimal("0.00"), adjustment_target=data["adjustment_target"], notes=data.get("notes", ""))
        if data.get("atta_quantity_kg"):
            BuybackLine.objects.create(transaction=tx, inventory_item=data["atta_inventory_item"], product_type=BuybackLine.ProductType.ATTA, quantity_kg=data["atta_quantity_kg"], system_rate_per_kg=self.atta_system_rate, applied_rate_per_kg=data["atta_rate_per_kg"], override_reason=data.get("atta_override_reason", ""))
        if data.get("khal_quantity_kg"):
            BuybackLine.objects.create(transaction=tx, inventory_item=data["khal_inventory_item"], product_type=BuybackLine.ProductType.KHAL, quantity_kg=data["khal_quantity_kg"], system_rate_per_kg=self.khal_system_rate, applied_rate_per_kg=data["khal_rate_per_kg"], override_reason=data.get("khal_override_reason", ""))
        tx.recalculate(); tx.save(update_fields=["buyback_value", "net_customer_payable", "updated_at"])
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
