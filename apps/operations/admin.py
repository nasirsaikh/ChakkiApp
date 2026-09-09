from django.contrib import admin

from .models import (
    BuybackLine,
    BuybackTransaction,
    GrindingOrder,
    GrindingOrderLine,
    Invoice,
    OrderPayment,
    OrderStatusEvent,
    ProductionLog,
    RateCard,
    UtilityLedger,
    WastageLog,
)


@admin.register(RateCard)
class RateCardAdmin(admin.ModelAdmin):
    list_display = ("grain_type", "flour_type", "with_jalan", "system_rate_per_kg", "minimum_rate_per_kg", "maximum_rate_per_kg", "is_active")
    list_filter = ("grain_type", "flour_type", "with_jalan", "is_active")
    search_fields = ("service_name",)


@admin.register(GrindingOrder)
class GrindingOrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "customer", "status", "payment_status", "created_at", "ready_at", "delivered_at")
    search_fields = ("order_number", "customer__name", "customer__phone")
    list_filter = ("status", "payment_status", "created_at")


@admin.register(OrderPayment)
class OrderPaymentAdmin(admin.ModelAdmin):
    list_display = ("payment_reference", "order", "amount", "payment_gateway", "settlement_status", "settled_at", "created_at")
    search_fields = ("payment_reference", "order__order_number", "provider")
    list_filter = ("settlement_status", "payment_method", "payment_gateway")
    readonly_fields = ("payment_reference", "provider_payload", "settled_at", "journal_entry", "created_at", "updated_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "order", "total_grinding_fee", "paid_amount", "forgiven_amount", "outstanding_amount", "status")
    search_fields = ("invoice_number", "order__order_number", "order__customer__name")
    list_filter = ("status",)
    readonly_fields = ("journal_entry",)


for model in [GrindingOrderLine, OrderStatusEvent, BuybackTransaction, BuybackLine, ProductionLog, WastageLog, UtilityLedger]:
    admin.site.register(model)

admin.site.site_header = "Chakki ERP Administration"
admin.site.site_title = "Chakki ERP Admin"
admin.site.index_title = "System configuration and operations"
