from django.contrib import admin
from .models import Customer
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "phone", "village", "customer_type", "opening_balance", "is_active")
    search_fields = ("code", "name", "phone", "village")
    list_filter = ("customer_type", "is_active", "village")
