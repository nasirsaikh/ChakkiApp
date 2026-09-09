from decimal import Decimal
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from apps.accounting.services import ensure_system_accounts
from apps.configuration.models import ChakkiSettings, PaymentGatewayConfig
from apps.inventory.models import InventoryItem
from apps.operations.models import RateCard

class Command(BaseCommand):
    help = "Seed system accounts, RBAC groups, default rate cards, settings and inventory masters."

    def handle(self, *args, **options):
        accounts = ensure_system_accounts()
        for role in ["Owner", "Manager", "Operator", "Accountant"]:
            Group.objects.get_or_create(name=role)
        ChakkiSettings.objects.get_or_create(
            pk=1,
            defaults={
                "brand_name": "Chakki ERP",
                "currency_code": "INR",
                "currency_symbol": "₹",
                "default_grinding_rate": Decimal("2.00"),
                "buyback_rates": {"KHAL": "20.00", "ATTA": "25.00", "OIL": "120.00", "BRAN": "15.00"},
            },
        )
        PaymentGatewayConfig.objects.get_or_create(
            name="UPI / Bank QR",
            defaults={
                "provider": PaymentGatewayConfig.Provider.UPI,
                "merchant_name": "Chakki ERP",
                "currency_code": "INR",
                "is_active": False,
                "is_default": False,
            },
        )
        rates = [
            (RateCard.GrainType.WHEAT, RateCard.FlourType.ATTA, False, "2.40", "2.00", "3.00"),
            (RateCard.GrainType.WHEAT, RateCard.FlourType.ATTA, True, "3.00", "2.50", "4.00"),
            (RateCard.GrainType.CHANA, RateCard.FlourType.BESAN, False, "3.00", "2.50", "4.00"),
            (RateCard.GrainType.MULTIGRAIN, RateCard.FlourType.MULTIGRAIN, False, "3.50", "3.00", "5.00"),
            (RateCard.GrainType.MUSTARD, RateCard.FlourType.OIL, False, "5.00", "4.00", "8.00"),
        ]
        for grain, flour, jalan, rate, minimum, maximum in rates:
            if not RateCard.objects.filter(grain_type=grain, flour_type=flour, with_jalan=jalan, is_active=True).exists():
                RateCard.objects.create(grain_type=grain, flour_type=flour, with_jalan=jalan, system_rate_per_kg=Decimal(rate), minimum_rate_per_kg=Decimal(minimum), maximum_rate_per_kg=Decimal(maximum))
        items = [
            ("RAW-WHEAT", "Wheat", InventoryItem.Category.RAW_GRAIN, InventoryItem.Unit.KG, "0", "100", "25", "0"),
            ("ATTA-PACK", "Packed Atta", InventoryItem.Category.FINISHED, InventoryItem.Unit.KG, "0", "50", "28", "32"),
            ("MUSTARD-OIL", "Mustard Oil", InventoryItem.Category.OIL, InventoryItem.Unit.LITRE, "0", "20", "110", "140"),
            ("KHAL", "Mustard Khal", InventoryItem.Category.BYPRODUCT, InventoryItem.Unit.KG, "0", "30", "18", "24"),
            ("GUNNY-BAG", "Gunny Bag", InventoryItem.Category.PACKAGING, InventoryItem.Unit.PIECE, "0", "25", "12", "15"),
        ]
        for sku, name, category, unit, qty, reorder, cost, selling in items:
            InventoryItem.objects.get_or_create(sku=sku, defaults={"name": name, "category": category, "unit": unit, "quantity_on_hand": Decimal(qty), "reorder_level": Decimal(reorder), "standard_cost": Decimal(cost), "selling_price": Decimal(selling)})
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(accounts)} system accounts, RBAC groups, rates, settings, payment gateway shell and inventory masters."))
