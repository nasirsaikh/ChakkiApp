from django import forms
from .models import Customer

BASE = "w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50"

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "village", "customer_type", "opening_balance", "notes", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = BASE
        if self.instance and self.instance.pk:
            self.fields["opening_balance"].disabled = True
            self.fields["opening_balance"].help_text = "Opening balance is an accounting event and cannot be edited after creation."
