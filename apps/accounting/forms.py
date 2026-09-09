from django import forms
from .models import CustomerReceipt, OldUdhaar

BASE = "w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50"

class CustomerReceiptForm(forms.ModelForm):
    class Meta:
        model = CustomerReceipt
        fields = ["customer", "amount", "payment_method", "reference", "receipt_date", "notes"]
        widgets = {"receipt_date": forms.DateInput(attrs={"type": "date"})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values(): f.widget.attrs["class"] = BASE

class OldUdhaarForm(forms.ModelForm):
    class Meta:
        model = OldUdhaar
        fields = ["customer", "original_amount", "opening_date", "note"]
        widgets = {"opening_date": forms.DateInput(attrs={"type": "date"})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values(): f.widget.attrs["class"] = BASE
