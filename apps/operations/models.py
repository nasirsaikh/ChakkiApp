from __future__ import annotations
from decimal import Decimal
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from apps.core.models import TimeStampedModel

MONEY = Decimal("0.01")

class RateCard(TimeStampedModel):
    class GrainType(models.TextChoices):
        WHEAT = "WHEAT", "Wheat"
        CHANA = "CHANA", "Chana"
        MULTIGRAIN = "MULTIGRAIN", "Multigrain"
        MUSTARD = "MUSTARD", "Mustard"
        OTHER = "OTHER", "Other"

    class FlourType(models.TextChoices):
        ATTA = "ATTA", "Atta"
        BESAN = "BESAN", "Besan"
        MULTIGRAIN = "MULTIGRAIN", "Multigrain"
        OIL = "OIL", "Oil extraction"
        OTHER = "OTHER", "Other"

    grain_type = models.CharField(max_length=20, choices=GrainType.choices, verbose_name="Grain")
    flour_type = models.CharField(max_length=20, choices=FlourType.choices, verbose_name="Output / service")
    service_name = models.CharField(max_length=120, blank=True, verbose_name="Custom service name")
    with_jalan = models.BooleanField(default=False, verbose_name="With Jalan")
    system_rate_per_kg = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))], verbose_name="System rate per kg")
    allow_override = models.BooleanField(default=True, verbose_name="Allow operator override")
    minimum_rate_per_kg = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"), verbose_name="Minimum allowed rate")
    maximum_rate_per_kg = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("999.00"), verbose_name="Maximum allowed rate")
    effective_from = models.DateField(default=timezone.localdate, verbose_name="Effective from")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        ordering = ["grain_type", "flour_type", "with_jalan"]
        constraints = [models.UniqueConstraint(fields=["grain_type", "flour_type", "with_jalan", "effective_from"], name="unique_rate_effective_date")]

    def clean(self) -> None:
        if self.minimum_rate_per_kg > self.system_rate_per_kg or self.system_rate_per_kg > self.maximum_rate_per_kg:
            raise ValidationError("System rate must lie between the minimum and maximum permitted rates.")

    def __str__(self) -> str:
        jalan = "with Jalan" if self.with_jalan else "without Jalan"
        return f"{self.get_grain_type_display()} / {self.get_flour_type_display()} ({jalan}) ₹{self.system_rate_per_kg}/kg"

class GrindingOrder(TimeStampedModel):
    class Status(models.TextChoices):
        INTAKE = "INTAKE", "Intake"
        GRINDING = "GRINDING", "Grinding Stage"
        READY = "READY", "Ready"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partially paid"
        PAID = "PAID", "Paid"

    order_number = models.CharField(max_length=24, unique=True, blank=True, verbose_name="Order number")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="grinding_orders", verbose_name="Customer")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INTAKE, db_index=True, verbose_name="Order status")
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID, db_index=True, verbose_name="Payment status")
    promised_at = models.DateTimeField(null=True, blank=True, verbose_name="Promised at")
    ready_at = models.DateTimeField(null=True, blank=True, verbose_name="Ready at")
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name="Delivered at")
    notes = models.TextField(blank=True, verbose_name="Order notes")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="chakki_orders_created")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"]), models.Index(fields=["customer", "created_at"])]

    def save(self, *args, **kwargs) -> None:
        if not self.order_number:
            self.order_number = f"GR-{timezone.localdate():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    @property
    def total_weight(self) -> Decimal:
        return sum((line.weight_kg for line in self.lines.all()), Decimal("0.00"))

    @property
    def total_fee(self) -> Decimal:
        return sum((line.line_total for line in self.lines.all()), Decimal("0.00"))

    def __str__(self) -> str:
        return self.order_number

class GrindingOrderLine(TimeStampedModel):
    order = models.ForeignKey(GrindingOrder, on_delete=models.CASCADE, related_name="lines", verbose_name="Grinding order")
    rate_card = models.ForeignKey(RateCard, on_delete=models.PROTECT, related_name="order_lines", verbose_name="Rate card")
    grain_type = models.CharField(max_length=20, choices=RateCard.GrainType.choices, verbose_name="Grain")
    flour_type = models.CharField(max_length=20, choices=RateCard.FlourType.choices, verbose_name="Output / service")
    weight_kg = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))], verbose_name="Weight (kg)")
    with_jalan = models.BooleanField(default=False, verbose_name="With Jalan")
    system_rate_per_kg = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="System rate per kg")
    applied_rate_per_kg = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Applied rate per kg")
    rate_override_reason = models.CharField(max_length=255, blank=True, verbose_name="Rate override reason")
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Line total")

    class Meta:
        ordering = ["id"]

    def clean(self) -> None:
        if self.rate_card_id:
            if self.with_jalan != self.rate_card.with_jalan or self.grain_type != self.rate_card.grain_type or self.flour_type != self.rate_card.flour_type:
                raise ValidationError("The selected rate card does not match the grain, output, and Jalan combination.")
            if self.applied_rate_per_kg != self.system_rate_per_kg:
                if not self.rate_card.allow_override:
                    raise ValidationError("This rate cannot be overridden.")
                if not (self.rate_card.minimum_rate_per_kg <= self.applied_rate_per_kg <= self.rate_card.maximum_rate_per_kg):
                    raise ValidationError("Applied rate is outside the permitted range.")
                if not self.rate_override_reason.strip():
                    raise ValidationError({"rate_override_reason": "A reason is required when overriding the system rate."})

    def save(self, *args, **kwargs) -> None:
        self.line_total = (self.weight_kg * self.applied_rate_per_kg).quantize(MONEY)
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.order.order_number} - {self.weight_kg}kg"

class OrderStatusEvent(TimeStampedModel):
    order = models.ForeignKey(GrindingOrder, on_delete=models.CASCADE, related_name="status_events")
    from_status = models.CharField(max_length=20, choices=GrindingOrder.Status.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=GrindingOrder.Status.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["created_at"]

class Invoice(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PARTIAL = "PARTIAL", "Partially paid"
        PAID = "PAID", "Paid"
        VOID = "VOID", "Void"

    order = models.OneToOneField(GrindingOrder, on_delete=models.PROTECT, related_name="invoice", verbose_name="Grinding order")
    invoice_number = models.CharField(max_length=24, unique=True, blank=True, verbose_name="Invoice number")
    total_grinding_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Total grinding fee")
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Paid amount")
    forgiven_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Forgiven amount")
    outstanding_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Outstanding udhaar")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, verbose_name="Invoice status")
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="grinding_invoice")

    class Meta:
        ordering = ["-created_at"]

    def clean(self) -> None:
        if min(self.total_grinding_fee, self.paid_amount, self.forgiven_amount) < 0:
            raise ValidationError("Invoice monetary amounts cannot be negative.")
        if self.paid_amount + self.forgiven_amount > self.total_grinding_fee:
            raise ValidationError("Paid plus forgiven amount cannot exceed the total grinding fee.")

    def save(self, *args, **kwargs) -> None:
        self.outstanding_amount = (self.total_grinding_fee - self.paid_amount - self.forgiven_amount).quantize(MONEY)
        if self.outstanding_amount == 0:
            self.status = self.Status.PAID
        elif self.paid_amount > 0:
            self.status = self.Status.PARTIAL
        elif self.status != self.Status.VOID:
            self.status = self.Status.OPEN
        self.full_clean()
        if not self.invoice_number:
            self.invoice_number = f"INV-{timezone.localdate():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.invoice_number

class OrderPayment(TimeStampedModel):
    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        QR = "QR", "Dynamic QR / UPI"
        CREDIT = "CREDIT", "Credit / Udhaar"
        BANK = "BANK", "Bank"
    class SettlementStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SETTLED = "SETTLED", "Settled"
        FAILED = "FAILED", "Failed"

    order = models.ForeignKey(GrindingOrder, on_delete=models.PROTECT, related_name="payments", verbose_name="Grinding order")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments", verbose_name="Invoice")
    payment_method = models.CharField(max_length=12, choices=PaymentMethod.choices, default=PaymentMethod.QR, verbose_name="Payment method")
    payment_reference = models.CharField(max_length=100, unique=True, db_index=True, verbose_name="Payment reference")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))], verbose_name="Payment amount")
    settlement_status = models.CharField(max_length=12, choices=SettlementStatus.choices, default=SettlementStatus.PENDING, db_index=True, verbose_name="Settlement status")
    provider = models.CharField(max_length=80, blank=True, verbose_name="Payment provider snapshot")
    payment_gateway = models.ForeignKey(
        "configuration.PaymentGatewayConfig",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order_payments",
        verbose_name="Payment / UPI gateway",
    )
    provider_payload = models.JSONField(default=dict, blank=True, verbose_name="Provider payload")
    settled_at = models.DateTimeField(null=True, blank=True, verbose_name="Settled at")
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="order_payment")

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs) -> None:
        if self.settlement_status == self.SettlementStatus.SETTLED and self.settled_at is None:
            self.settled_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.payment_reference

class BuybackTransaction(TimeStampedModel):
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="buybacks", verbose_name="Customer")
    order = models.ForeignKey(GrindingOrder, on_delete=models.PROTECT, null=True, blank=True, related_name="buybacks", verbose_name="Related order")
    reference = models.CharField(max_length=24, unique=True, blank=True, verbose_name="Buyback reference")
    processing_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Processing / extraction fee")
    buyback_value = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Products bought back value")
    net_customer_payable = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Net amount payable to customer")
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="buyback")
    notes = models.CharField(max_length=255, blank=True, verbose_name="Notes")

    class Meta:
        ordering = ["-created_at"]

    def recalculate(self) -> None:
        self.buyback_value = sum((line.line_value for line in self.lines.all()), Decimal("0.00"))
        self.net_customer_payable = (self.buyback_value - self.processing_fee).quantize(MONEY)

    def save(self, *args, **kwargs) -> None:
        if not self.reference:
            self.reference = f"BB-{timezone.localdate():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.reference

class BuybackLine(TimeStampedModel):
    class ProductType(models.TextChoices):
        KHAL = "KHAL", "Khal"
        ATTA = "ATTA", "Atta"
        OIL = "OIL", "Oil"
        BRAN = "BRAN", "Bran / Chokar"
        OTHER = "OTHER", "Other"

    transaction = models.ForeignKey(BuybackTransaction, on_delete=models.CASCADE, related_name="lines")
    inventory_item = models.ForeignKey("inventory.InventoryItem", on_delete=models.PROTECT, related_name="buyback_lines", verbose_name="Inventory item")
    product_type = models.CharField(max_length=20, choices=ProductType.choices, verbose_name="Product")
    quantity_kg = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))], verbose_name="Quantity (kg)")
    system_rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="System buyback rate")
    applied_rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Applied buyback rate")
    override_reason = models.CharField(max_length=255, blank=True, verbose_name="Override reason")
    line_value = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Line value")

    def clean(self) -> None:
        if self.applied_rate_per_kg != self.system_rate_per_kg and not self.override_reason.strip():
            raise ValidationError({"override_reason": "Enter a reason when changing the system buyback rate."})

    def save(self, *args, **kwargs) -> None:
        self.line_value = (self.quantity_kg * self.applied_rate_per_kg).quantize(MONEY)
        self.full_clean()
        super().save(*args, **kwargs)

class ProductionLog(TimeStampedModel):
    production_date = models.DateField(default=timezone.localdate, db_index=True, verbose_name="Production date")
    product_name = models.CharField(max_length=120, verbose_name="Product")
    input_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))], verbose_name="Input raw weight (kg)")
    output_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0.000"))], verbose_name="Finished output (kg)")
    byproduct_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="By-product output (kg)")
    process_loss_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="Process loss (kg)")
    notes = models.CharField(max_length=255, blank=True)

    def clean(self) -> None:
        accounted = self.output_weight_kg + self.byproduct_weight_kg + self.process_loss_kg
        if accounted > self.input_weight_kg + Decimal("0.050"):
            raise ValidationError("Output + by-product + loss cannot materially exceed input weight.")

    @property
    def yield_percent(self) -> Decimal:
        return ((self.output_weight_kg / self.input_weight_kg) * 100).quantize(Decimal("0.01")) if self.input_weight_kg else Decimal("0")

class WastageLog(TimeStampedModel):
    wastage_date = models.DateField(default=timezone.localdate, db_index=True, verbose_name="Wastage date")
    process = models.CharField(max_length=120, verbose_name="Process")
    input_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="Reference input (kg)")
    milling_loss_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="Milling loss (kg)")
    dust_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="Dust (kg)")
    other_waste_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="Other waste (kg)")
    reason = models.CharField(max_length=255, blank=True, verbose_name="Reason")

    @property
    def total_waste_kg(self) -> Decimal:
        return self.milling_loss_kg + self.dust_kg + self.other_waste_kg

class UtilityLedger(TimeStampedModel):
    class UtilityType(models.TextChoices):
        ELECTRICITY = "ELECTRICITY", "Electricity"
        DIESEL = "DIESEL", "Diesel / Fuel"
        WATER = "WATER", "Water"
        OTHER = "OTHER", "Other overhead"
    period = models.DateField(default=timezone.localdate, db_index=True, verbose_name="Billing / usage date")
    utility_type = models.CharField(max_length=20, choices=UtilityType.choices, verbose_name="Utility type")
    units = models.DecimalField(max_digits=12, decimal_places=3, default=0, verbose_name="Units / quantity")
    unit_label = models.CharField(max_length=20, default="unit", verbose_name="Unit label")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Cost")
    reference = models.CharField(max_length=80, blank=True, verbose_name="Bill reference")
    notes = models.CharField(max_length=255, blank=True)
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="utility_cost")
