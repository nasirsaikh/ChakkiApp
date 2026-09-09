from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from apps.customers.models import Customer
from apps.operations.models import GrindingOrder, GrindingOrderLine, RateCard
from apps.operations.services import finalize_invoice
from .models import LedgerEntry
from .services import ensure_system_accounts

class AccountingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner", password="x")
        self.customer = Customer.objects.create(name="Test Customer")
        self.rate = RateCard.objects.create(grain_type=RateCard.GrainType.WHEAT, flour_type=RateCard.FlourType.ATTA, with_jalan=False, system_rate_per_kg=Decimal("2.40"), minimum_rate_per_kg=Decimal("2.00"), maximum_rate_per_kg=Decimal("3.00"))
        self.accounts = ensure_system_accounts()

    def test_forgiveness_never_flows_to_udhaar(self):
        order = GrindingOrder.objects.create(customer=self.customer, created_by=self.user)
        GrindingOrderLine.objects.create(order=order, rate_card=self.rate, grain_type=self.rate.grain_type, flour_type=self.rate.flour_type, weight_kg=Decimal("20"), with_jalan=False, system_rate_per_kg=Decimal("2.40"), applied_rate_per_kg=Decimal("2.40"))
        invoice = finalize_invoice(order, paid_amount=Decimal("40"), forgiven_amount=Decimal("3"), created_by=self.user)
        invoice.refresh_from_db()
        self.assertEqual(invoice.total_grinding_fee, Decimal("48.00"))
        self.assertEqual(invoice.paid_amount, Decimal("40.00"))
        self.assertEqual(invoice.forgiven_amount, Decimal("3.00"))
        self.assertEqual(invoice.outstanding_amount, Decimal("5.00"))
        ar_debit = LedgerEntry.objects.filter(account=self.accounts["AR"], customer=self.customer).aggregate(v=__import__('django.db.models', fromlist=['Sum']).Sum("debit"))["v"]
        ar_credit = LedgerEntry.objects.filter(account=self.accounts["AR"], customer=self.customer).aggregate(v=__import__('django.db.models', fromlist=['Sum']).Sum("credit"))["v"]
        goodwill = LedgerEntry.objects.filter(account=self.accounts["GOODWILL_EXPENSE"], customer=self.customer).aggregate(v=__import__('django.db.models', fromlist=['Sum']).Sum("debit"))["v"]
        self.assertEqual(ar_debit - ar_credit, Decimal("5.00"))
        self.assertEqual(goodwill, Decimal("3.00"))

    def test_each_journal_is_balanced(self):
        order = GrindingOrder.objects.create(customer=self.customer)
        GrindingOrderLine.objects.create(order=order, rate_card=self.rate, grain_type=self.rate.grain_type, flour_type=self.rate.flour_type, weight_kg=Decimal("10"), with_jalan=False, system_rate_per_kg=Decimal("2.40"), applied_rate_per_kg=Decimal("2.40"))
        invoice = finalize_invoice(order, forgiven_amount=Decimal("1"))
        journal = invoice.journal_entry
        self.assertEqual(sum(x.debit for x in journal.lines.all()), sum(x.credit for x in journal.lines.all()))
