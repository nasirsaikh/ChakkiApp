from django.contrib import admin
from .models import Supplier, InventoryItem, InventoryMovement, Purchase, PurchaseLine, Sale, SaleLine
for model in [Supplier, InventoryItem, InventoryMovement, Purchase, PurchaseLine, Sale, SaleLine]: admin.site.register(model)
