from django.contrib import messages
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from apps.accounting.services import record_old_udhaar
from apps.core.rbac import module_required
from .forms import CustomerForm
from .models import Customer

@module_required("customers")
def customer_list(request: HttpRequest) -> HttpResponse:
    q = request.GET.get("q", "").strip()
    customers = Customer.objects.all()
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(phone__icontains=q) | Q(village__icontains=q))
    template = "customers/_customer_table.html" if request.headers.get("HX-Request") == "true" and request.GET.get("partial") else "customers/list.html"
    return render(request, template, {"customers": customers[:200], "q": q})

@module_required("customers")
def customer_create(request: HttpRequest) -> HttpResponse:
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        customer = form.save()
        if customer.opening_balance > 0:
            record_old_udhaar(customer, customer.opening_balance, created_by=request.user)
        messages.success(request, "Customer created successfully.")
        return redirect("customers:detail", pk=customer.pk)
    return render(request, "core/form.html", {"form": form, "title": "Add Customer", "cancel_url": "customers:list"})

@module_required("customers")
def customer_edit(request: HttpRequest, pk: int) -> HttpResponse:
    customer = get_object_or_404(Customer, pk=pk)
    original_opening = customer.opening_balance
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        updated = form.save()
        if original_opening == 0 and updated.opening_balance > 0 and not updated.old_udhaar_records.exists():
            record_old_udhaar(updated, updated.opening_balance, created_by=request.user)
        messages.success(request, "Customer updated.")
        return redirect("customers:detail", pk=updated.pk)
    return render(request, "core/form.html", {"form": form, "title": "Edit Customer", "cancel_url": "customers:detail", "cancel_kwargs": {"pk": pk}})

@module_required("customers")
def customer_detail(request: HttpRequest, pk: int) -> HttpResponse:
    customer = get_object_or_404(Customer.objects.prefetch_related("grinding_orders__lines", "receipts"), pk=pk)
    return render(request, "customers/detail.html", {"customer": customer})
