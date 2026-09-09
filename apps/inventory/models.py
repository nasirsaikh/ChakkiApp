from __future__ import annotations
from decimal import Decimal
import uuid
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from apps.core.models import TimeStampedModel

class Supplier(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True, blank=True, verbose_name="Supplier code")
    name = models.CharField(max_length=150, db_index=True, verbose_name="Supplier name")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Phone")
    address = models.TextField(blank=True, verbose_name="Address")
    gstin = models.CharField(max_length=20, blank=True, verbose_name="GSTIN")
    opening_payable = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Opening payable")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs) -> None:
        if not self.code:
            self.code = f"S-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name

class InventoryItem(TimeStampedModel):
    class Category(models.TextChoices):
        RAW_GRAIN = "RAW_GRAIN", "Raw grain"
        FINISHED = "FINISHED", "Ground atta / finished flour"
        OIL = "OIL", "Cold-press oil"
        BYPRODUCT = "BYPRODUCT", "Khal / by-product"
        PACKAGING = "PACKAGING", "Gunny bag / packaging"
        SPARE = "SPARE", "Machine spare"
        OTHER = "OTHER", "Other"
    class Unit(models.TextChoices):
        KG = "KG", "Kg"
        LITRE = "LITRE", "Litre"
        PIECE = "PIECE", "Piece"
        BAG = "BAG", "Bag"

    sku = models.CharField(max_length=30, unique=True, verbose_name="SKU")
    name = models.CharField(max_length=120, verbose_name="Item name")
    category = models.CharField(max_length=20, choices=Category.choices, verbose_name="Category")
    unit = models.CharField(max_length=12, choices=Unit.choices, default=Unit.KG, verbose_name="Unit")
    quantity_on_hand = models.DecimalField(max_digits=14, decimal_places=3, default=0, verbose_name="Quantity on hand")
    reorder_level = models.DecimalField(max_digits=14, decimal_places=3, default=0, verbose_name="Reorder level")
    standard_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Standard cost per unit")
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Selling price per unit")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        ordering = ["category", "name"]

    @property
    def needs_reorder(self) -> bool:
        return self.quantity_on_hand <= self.reorder_level

    def __str__(self) -> str:
        return f"{self.name} ({self.quantity_on_hand} {self.get_unit_display()})"

class InventoryMovement(TimeStampedModel):
    class MovementType(models.TextChoices):
        OPENING = "OPENING", "Opening stock"
        PURCHASE = "PURCHASE", "Purchase receipt"
        SALE = "SALE", "Retail sale"
        PRODUCTION_IN = "PRODUCTION_IN", "Production output"
        PRODUCTION_OUT = "PRODUCTION_OUT", "Production input"
        BUYBACK = "BUYBACK", "Customer buyback"
        WASTAGE = "WASTAGE", "Wastage"
        ADJUSTMENT = "ADJUSTMENT", "Stock adjustment"

    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="movements", verbose_name="Inventory item")
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, verbose_name="Movement type")
    quantity_delta = models.DecimalField(max_digits=14, decimal_places=3, verbose_name="Quantity change")
    reference = models.CharField(max_length=80, blank=True, db_index=True, verbose_name="Reference")
    notes = models.CharField(max_length=255, blank=True, verbose_name="Notes")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Occurred at")
    balance_after = models.DecimalField(max_digits=14, decimal_places=3, verbose_name="Balance after movement")

    class Meta:
        ordering = ["-occurred_at", "-id"]

class Purchase(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        POSTED = "POSTED", "Posted"
        CANCELLED = "CANCELLED", "Cancelled"

    purchase_number = models.CharField(max_length=24, unique=True, blank=True, verbose_name="Purchase number")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases", verbose_name="Supplier")
    invoice_reference = models.CharField(max_length=80, blank=True, verbose_name="Supplier invoice reference")
    purchase_date = models.DateField(default=timezone.localdate, verbose_name="Purchase date")
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name="Total purchase amount")
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name="Amount paid")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, verbose_name="Status")
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="purchase")

    @property
    def outstanding_amount(self) -> Decimal:
        return max(self.total_amount - self.amount_paid, Decimal("0.00"))

    def save(self, *args, **kwargs) -> None:
        if not self.purchase_number:
            self.purchase_number = f"PUR-{timezone.localdate():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.purchase_number

class PurchaseLine(TimeStampedModel):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="purchase_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def save(self, *args, **kwargs) -> None:
        self.line_total = (self.quantity * self.unit_cost).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

class Sale(TimeStampedModel):
    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        UPI = "UPI", "UPI / QR"
        CREDIT = "CREDIT", "Credit / Udhaar"

    sale_number = models.CharField(max_length=24, unique=True, blank=True, verbose_name="Sale number")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="retail_sales", verbose_name="Customer")
    sale_date = models.DateField(default=timezone.localdate, verbose_name="Sale date")
    payment_method = models.CharField(max_length=12, choices=PaymentMethod.choices, default=PaymentMethod.CASH, verbose_name="Payment method")
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name="Total sale amount")
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="retail_sale")

    def save(self, *args, **kwargs) -> None:
        if not self.sale_number:
            self.sale_number = f"SAL-{timezone.localdate():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.sale_number

class SaleLine(TimeStampedModel):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="sale_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def save(self, *args, **kwargs) -> None:
        self.line_total = (self.quantity * self.unit_price).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
