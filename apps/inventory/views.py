from decimal import Decimal
from django.contrib import messages
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from apps.accounting.services import ensure_system_accounts, post_journal
from apps.core.rbac import module_required
from .forms import InventoryItemForm, PurchaseEntryForm, SaleEntryForm, SupplierForm
from .models import InventoryItem, Purchase, Sale, Supplier
from .services import post_purchase, post_sale

@module_required("inventory")
def stock(request: HttpRequest) -> HttpResponse:
    form = InventoryItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = form.save()
        messages.success(request, f"Inventory item {item.name} saved.")
        return redirect("inventory:stock")
    return render(request, "inventory/stock.html", {"items": InventoryItem.objects.filter(is_active=True), "form": form})

@module_required("purchases")
def purchases(request: HttpRequest) -> HttpResponse:
    form = PurchaseEntryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        purchase = form.save(); post_purchase(purchase, created_by=request.user)
        messages.success(request, f"Purchase {purchase.purchase_number} posted.")
        return redirect("inventory:purchases")
    return render(request, "inventory/purchases.html", {"form": form, "purchases": Purchase.objects.select_related("supplier").prefetch_related("lines__item")[:100]})

@module_required("sales")
def sales(request: HttpRequest) -> HttpResponse:
    form = SaleEntryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        sale = form.save(); post_sale(sale, created_by=request.user)
        messages.success(request, f"Sale {sale.sale_number} posted.")
        return redirect("inventory:sales")
    return render(request, "inventory/sales.html", {"form": form, "sales": Sale.objects.select_related("customer").prefetch_related("lines__item")[:100]})

@module_required("suppliers")
def suppliers(request: HttpRequest) -> HttpResponse:
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        supplier = form.save()
        if supplier.opening_payable > 0 and not supplier.ledger_entries.exists():
            accounts = ensure_system_accounts()
            post_journal(
                narration=f"Opening payable for {supplier.name}", source_type="supplier_opening", source_id=supplier.pk, created_by=request.user,
                lines=[
                    {"account": accounts["OPENING_EQUITY"], "debit": supplier.opening_payable, "credit": 0, "supplier": supplier},
                    {"account": accounts["AP"], "debit": 0, "credit": supplier.opening_payable, "supplier": supplier},
                ],
            )
        messages.success(request, "Supplier saved.")
        return redirect("inventory:suppliers")
    accounts = ensure_system_accounts()
    rows = []
    for supplier in Supplier.objects.all():
        agg = supplier.ledger_entries.filter(account=accounts["AP"]).aggregate(d=Sum("debit"), c=Sum("credit"))
        rows.append((supplier, (agg["c"] or Decimal("0")) - (agg["d"] or Decimal("0"))))
    return render(request, "inventory/suppliers.html", {"form": form, "rows": rows})
