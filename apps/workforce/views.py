from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from apps.core.rbac import module_required
from .forms import AttendanceForm, EmployeeForm, MaintenanceLogForm, PayrollRunForm
from .models import Attendance, Employee, MaintenanceLog, PayrollRun
from .services import generate_payroll, post_maintenance, post_payroll

@module_required("employees")
def employees(request: HttpRequest) -> HttpResponse:
    form = EmployeeForm(request.POST or None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Employee saved."); return redirect("workforce:employees")
    return render(request, "workforce/employees.html", {"form": form, "employees": Employee.objects.all()})

@module_required("attendance")
def attendance(request: HttpRequest) -> HttpResponse:
    form = AttendanceForm(request.POST or None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Attendance saved."); return redirect("workforce:attendance")
    return render(request, "workforce/attendance.html", {"form": form, "records": Attendance.objects.select_related("employee")[:150]})

@module_required("payroll")
def payroll(request: HttpRequest) -> HttpResponse:
    form = PayrollRunForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        run = form.save(); generate_payroll(run); messages.success(request, "Payroll calculated from attendance."); return redirect("workforce:payroll")
    return render(request, "workforce/payroll.html", {"form": form, "runs": PayrollRun.objects.prefetch_related("lines__employee")[:50]})

@module_required("payroll")
@require_POST
def payroll_post(request: HttpRequest, pk: int) -> HttpResponse:
    run = PayrollRun.objects.get(pk=pk); post_payroll(run, created_by=request.user); messages.success(request, "Payroll posted to accounts."); return redirect("workforce:payroll")

@module_required("maintenance")
def maintenance(request: HttpRequest) -> HttpResponse:
    form = MaintenanceLogForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        log = form.save(); post_maintenance(log, created_by=request.user); messages.success(request, "Maintenance log saved."); return redirect("workforce:maintenance")
    return render(request, "workforce/maintenance.html", {"form": form, "logs": MaintenanceLog.objects.order_by("-maintenance_date")[:100]})
