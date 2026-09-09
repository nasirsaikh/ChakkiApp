from django.db import migrations, models
import django.core.validators
from decimal import Decimal


class Migration(migrations.Migration):
    dependencies = [("operations", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="orderpayment",
            name="current_invoice_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal("0.00"))], verbose_name="Current invoice allocation"),
        ),
        migrations.AddField(
            model_name="orderpayment",
            name="old_udhaar_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal("0.00"))], verbose_name="Old udhaar allocation"),
        ),
        migrations.AddField(
            model_name="buybacktransaction",
            name="adjustment_target",
            field=models.CharField(choices=[("AUTO", "Current bill, then old udhaar, then cash"), ("CURRENT", "Current grinding bill / udhaar"), ("OLD", "Old udhaar"), ("CASH", "Cash payout")], default="CASH", max_length=12, verbose_name="Buyback adjustment target"),
        ),
        migrations.AddField(
            model_name="buybacktransaction",
            name="adjusted_current_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="Adjusted against current bill"),
        ),
        migrations.AddField(
            model_name="buybacktransaction",
            name="adjusted_old_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="Adjusted against old udhaar"),
        ),
        migrations.AddField(
            model_name="buybacktransaction",
            name="cash_paid_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="Cash paid to customer"),
        ),
        migrations.RunSQL(
            sql="UPDATE operations_orderpayment SET current_invoice_amount = amount WHERE current_invoice_amount = 0 AND old_udhaar_amount = 0;",
            reverse_sql="UPDATE operations_orderpayment SET current_invoice_amount = 0;",
        ),
    ]
