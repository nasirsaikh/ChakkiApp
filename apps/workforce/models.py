from __future__ import annotations
from decimal import Decimal
import uuid
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from apps.core.models import TimeStampedModel

class Employee(TimeStampedModel):
    class EmploymentType(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly salary"
        DAILY = "DAILY", "Daily wage"
        CONTRACT = "CONTRACT", "Contract"
    class EmploymentStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ON_LEAVE = "ON_LEAVE", "On leave"
        INACTIVE = "INACTIVE", "Inactive"

    employee_code = models.CharField(max_length=20, unique=True, blank=True, verbose_name="Employee code")
    name = models.CharField(max_length=120, verbose_name="Employee name")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Phone")
    role_title = models.CharField(max_length=80, blank=True, verbose_name="Role / job title")
    employment_type = models.CharField(max_length=12, choices=EmploymentType.choices, default=EmploymentType.DAILY, verbose_name="Employment type")
    status = models.CharField(max_length=12, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVE, verbose_name="Employment status")
    monthly_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0"))], verbose_name="Monthly salary")
    daily_wage = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0"))], verbose_name="Daily wage")
    joined_on = models.DateField(default=timezone.localdate, verbose_name="Joined on")
    contract_notes = models.TextField(blank=True, verbose_name="Contract parameters")

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs) -> None:
        if not self.employee_code:
            self.employee_code = f"E-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.employee_code} - {self.name}"

class Attendance(TimeStampedModel):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        ABSENT = "ABSENT", "Absent"
        HALF_DAY = "HALF_DAY", "Half day"
        LEAVE = "LEAVE", "Leave"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance_records", verbose_name="Employee")
    attendance_date = models.DateField(default=timezone.localdate, db_index=True, verbose_name="Date")
    check_in = models.TimeField(null=True, blank=True, verbose_name="Check in")
    check_out = models.TimeField(null=True, blank=True, verbose_name="Check out")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PRESENT, verbose_name="Attendance status")
    notes = models.CharField(max_length=255, blank=True, verbose_name="Notes")

    class Meta:
        ordering = ["-attendance_date", "employee__name"]
        constraints = [models.UniqueConstraint(fields=["employee", "attendance_date"], name="unique_employee_attendance_day")]

    def clean(self) -> None:
        if self.check_in and self.check_out and self.check_out <= self.check_in:
            raise ValidationError("Check-out must be later than check-in.")

class PayrollRun(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        POSTED = "POSTED", "Posted"
        PAID = "PAID", "Paid"

    period_start = models.DateField(verbose_name="Period start")
    period_end = models.DateField(verbose_name="Period end")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, verbose_name="Status")
    total_net_pay = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name="Total net pay")
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="payroll_run")

    class Meta:
        ordering = ["-period_end"]
        constraints = [models.UniqueConstraint(fields=["period_start", "period_end"], name="unique_payroll_period")]

    def clean(self) -> None:
        if self.period_end < self.period_start:
            raise ValidationError("Payroll period end cannot be before start.")

    def __str__(self) -> str:
        return f"Payroll {self.period_start} to {self.period_end}"

class PayrollLine(TimeStampedModel):
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="payroll_lines")
    workdays = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="Active workdays")
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Gross pay")
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Deductions")
    advances = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Advances")
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Net pay")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["payroll_run", "employee"], name="unique_payroll_employee")]

class MaintenanceLog(TimeStampedModel):
    class ServiceType(models.TextChoices):
        BELT = "BELT", "Belt replacement"
        BEARING = "BEARING", "Bearing lubrication / replacement"
        STONE = "STONE", "Stone channelling / Takai"
        MOTOR = "MOTOR", "Motor service"
        CLEANING = "CLEANING", "Cleaning"
        OTHER = "OTHER", "Other"

    maintenance_date = models.DateField(default=timezone.localdate, db_index=True, verbose_name="Maintenance date")
    machine_name = models.CharField(max_length=120, verbose_name="Machine")
    service_type = models.CharField(max_length=20, choices=ServiceType.choices, verbose_name="Service type")
    meter_hours = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True, verbose_name="Machine hours")
    next_due_date = models.DateField(null=True, blank=True, verbose_name="Next due date")
    next_due_hours = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True, verbose_name="Next due machine hours")
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(Decimal("0"))], verbose_name="Maintenance cost")
    performed_by = models.CharField(max_length=120, blank=True, verbose_name="Performed by")
    details = models.TextField(blank=True, verbose_name="Details")
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True, related_name="maintenance_log")
