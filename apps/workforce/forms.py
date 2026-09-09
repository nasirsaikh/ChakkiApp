from django import forms
from .models import Attendance, Employee, MaintenanceLog, PayrollRun
BASE = "w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50"

class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values(): f.widget.attrs["class"] = BASE

class EmployeeForm(StyledModelForm):
    class Meta:
        model = Employee
        fields = ["name", "phone", "role_title", "employment_type", "status", "monthly_salary", "daily_wage", "joined_on", "contract_notes"]
        widgets = {"joined_on": forms.DateInput(attrs={"type": "date"}), "contract_notes": forms.Textarea(attrs={"rows": 3})}

class AttendanceForm(StyledModelForm):
    class Meta:
        model = Attendance
        fields = ["employee", "attendance_date", "check_in", "check_out", "status", "notes"]
        widgets = {"attendance_date": forms.DateInput(attrs={"type": "date"}), "check_in": forms.TimeInput(attrs={"type": "time"}), "check_out": forms.TimeInput(attrs={"type": "time"})}

class PayrollRunForm(StyledModelForm):
    class Meta:
        model = PayrollRun
        fields = ["period_start", "period_end"]
        widgets = {"period_start": forms.DateInput(attrs={"type": "date"}), "period_end": forms.DateInput(attrs={"type": "date"})}

class MaintenanceLogForm(StyledModelForm):
    class Meta:
        model = MaintenanceLog
        fields = ["maintenance_date", "machine_name", "service_type", "meter_hours", "next_due_date", "next_due_hours", "cost", "performed_by", "details"]
        widgets = {"maintenance_date": forms.DateInput(attrs={"type": "date"}), "next_due_date": forms.DateInput(attrs={"type": "date"}), "details": forms.Textarea(attrs={"rows": 3})}
