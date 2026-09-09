from django import forms
from django.db import transaction
from .models import InventoryItem, Purchase, PurchaseLine, Sale, SaleLine, Supplier

BASE = "w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50"
CHECK = "h-5 w-5 rounded border-slate-300 text-emerald-600"

class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values(): f.widget.attrs["class"] = CHECK if isinstance(f.widget, forms.CheckboxInput) else BASE

class SupplierForm(StyledModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "phone", "address", "gstin", "opening_payable", "is_active"]

class InventoryItemForm(StyledModelForm):
    class Meta:
        model = InventoryItem
        fields = ["sku", "name", "category", "unit", "quantity_on_hand", "reorder_level", "standard_cost", "selling_price", "is_active"]

class PurchaseEntryForm(forms.Form):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True))
    invoice_reference = forms.CharField(required=False)
    item = forms.ModelChoiceField(queryset=InventoryItem.objects.filter(is_active=True))
    quantity = forms.DecimalField(min_value=0.001, max_digits=14, decimal_places=3)
    unit_cost = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2)
    amount_paid = forms.DecimalField(min_value=0, max_digits=14, decimal_places=2, initial=0)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values(): f.widget.attrs["class"] = BASE
    def clean(self):
        d = super().clean()
        if d.get("quantity") is not None and d.get("unit_cost") is not None and (d.get("amount_paid") or 0) > d["quantity"] * d["unit_cost"]:
            self.add_error("amount_paid", "Paid amount cannot exceed purchase total.")
        return d
    @transaction.atomic
    def save(self):
        d = self.cleaned_data
        p = Purchase.objects.create(supplier=d["supplier"], invoice_reference=d["invoice_reference"], amount_paid=d["amount_paid"])
        PurchaseLine.objects.create(purchase=p, item=d["item"], quantity=d["quantity"], unit_cost=d["unit_cost"])
        return p

class SaleEntryForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=__import__('apps.customers.models', fromlist=['Customer']).Customer.objects.filter(is_active=True), required=False)
    item = forms.ModelChoiceField(queryset=InventoryItem.objects.filter(is_active=True))
    quantity = forms.DecimalField(min_value=0.001, max_digits=14, decimal_places=3)
    unit_price = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, required=False)
    payment_method = forms.ChoiceField(choices=Sale.PaymentMethod.choices)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values(): f.widget.attrs["class"] = BASE
    def clean(self):
        d = super().clean()
        item = d.get("item")
        if item and d.get("unit_price") is None:
            d["unit_price"] = item.selling_price
        if d.get("payment_method") == Sale.PaymentMethod.CREDIT and not d.get("customer"):
            self.add_error("customer", "A customer is required for a credit sale.")
        if item and d.get("quantity") and d["quantity"] > item.quantity_on_hand:
            self.add_error("quantity", f"Only {item.quantity_on_hand} {item.get_unit_display()} available.")
        return d
    @transaction.atomic
    def save(self):
        d = self.cleaned_data
        s = Sale.objects.create(customer=d["customer"], payment_method=d["payment_method"])
        SaleLine.objects.create(sale=s, item=d["item"], quantity=d["quantity"], unit_price=d["unit_price"], unit_cost=d["item"].standard_cost)
        return s
