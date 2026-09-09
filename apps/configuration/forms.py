from django import forms

SHADCN_FIELD = "w-full rounded-md border border-input bg-background px-3 py-2.5 text-sm text-foreground shadow-xs outline-none transition placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/25 disabled:cursor-not-allowed disabled:opacity-50"


class ReadOnlyConfigurationForm(forms.Form):
    """Kept as a stable import surface; mutable system settings are administered only in Django Admin."""
