from __future__ import annotations
from decimal import Decimal
import uuid
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from apps.core.models import TimeStampedModel

phone_validator = RegexValidator(regex=r"^[0-9+ -]{7,20}$", message="Enter a valid phone number.")

class Customer(TimeStampedModel):
    class CustomerType(models.TextChoices):
        PERMANENT = "PERMANENT", "Permanent"
        TEMPORARY = "TEMPORARY", "Temporary"

    code = models.CharField(max_length=20, unique=True, blank=True, verbose_name="Customer code")
    name = models.CharField(max_length=120, db_index=True, verbose_name="Customer name")
    phone = models.CharField(max_length=20, blank=True, validators=[phone_validator], db_index=True, verbose_name="Phone")
    village = models.CharField(max_length=120, blank=True, db_index=True, verbose_name="Village")
    customer_type = models.CharField(max_length=20, choices=CustomerType.choices, default=CustomerType.PERMANENT, verbose_name="Customer type")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0.00"))], verbose_name="Opening udhaar balance")
    notes = models.TextField(blank=True, verbose_name="Notes")
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        ordering = ["name"]
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
        indexes = [models.Index(fields=["name", "phone", "village"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs) -> None:
        if not self.code:
            self.code = f"C-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)
