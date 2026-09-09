from __future__ import annotations
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from apps.accounting.services import ensure_system_accounts, post_journal
from .models import Attendance, Employee, MaintenanceLog, PayrollLine, PayrollRun

@transaction.atomic
def generate_payroll(run: PayrollRun) -> PayrollRun:
    run = PayrollRun.objects.select_for_update().get(pk=run.pk)
    if run.status != PayrollRun.Status.DRAFT:
        return run
    run.lines.all().delete()
    total = Decimal("0.00")
    employees = Employee.objects.filter(status=Employee.EmploymentStatus.ACTIVE)
    for employee in employees:
        records = Attendance.objects.filter(employee=employee, attendance_date__range=(run.period_start, run.period_end))
        workdays = Decimal(records.filter(status=Attendance.Status.PRESENT).count()) + Decimal("0.5") * Decimal(records.filter(status=Attendance.Status.HALF_DAY).count())
        if employee.employment_type == Employee.EmploymentType.MONTHLY:
            calendar_days = Decimal((run.period_end - run.period_start).days + 1)
            gross = (employee.monthly_salary / calendar_days * workdays).quantize(Decimal("0.01")) if calendar_days else Decimal("0")
        else:
            gross = (employee.daily_wage * workdays).quantize(Decimal("0.01"))
        line = PayrollLine.objects.create(payroll_run=run, employee=employee, workdays=workdays, gross_pay=gross, net_pay=gross)
        total += line.net_pay
    run.total_net_pay = total
    run.save(update_fields=["total_net_pay", "updated_at"])
    return run

@transaction.atomic
def post_payroll(run: PayrollRun, created_by=None) -> PayrollRun:
    run = PayrollRun.objects.select_for_update().get(pk=run.pk)
    if run.journal_entry_id:
        return run
    if run.status == PayrollRun.Status.DRAFT:
        generate_payroll(run)
        run.refresh_from_db()
    accounts = ensure_system_accounts()
    if run.total_net_pay > 0:
        journal = post_journal(
            narration=str(run), source_type="payroll", source_id=run.pk, entry_date=run.period_end, created_by=created_by,
            lines=[
                {"account": accounts["WAGE_EXPENSE"], "debit": run.total_net_pay, "credit": 0},
                {"account": accounts["CASH"], "debit": 0, "credit": run.total_net_pay},
            ],
        )
        run.journal_entry = journal
    run.status = PayrollRun.Status.POSTED
    run.save(update_fields=["status", "journal_entry", "updated_at"])
    return run

@transaction.atomic
def post_maintenance(log: MaintenanceLog, created_by=None) -> MaintenanceLog:
    if log.journal_entry_id or log.cost <= 0:
        return log
    accounts = ensure_system_accounts()
    journal = post_journal(
        narration=f"Maintenance: {log.machine_name} / {log.get_service_type_display()}", source_type="maintenance", source_id=log.pk, entry_date=log.maintenance_date, created_by=created_by,
        lines=[
            {"account": accounts["MAINTENANCE_EXPENSE"], "debit": log.cost, "credit": 0},
            {"account": accounts["CASH"], "debit": 0, "credit": log.cost},
        ],
    )
    log.journal_entry = journal
    log.save(update_fields=["journal_entry", "updated_at"])
    return log
