from django.contrib import admin
from .models import Employee, Attendance, PayrollRun, PayrollLine, MaintenanceLog
for model in [Employee, Attendance, PayrollRun, PayrollLine, MaintenanceLog]: admin.site.register(model)
