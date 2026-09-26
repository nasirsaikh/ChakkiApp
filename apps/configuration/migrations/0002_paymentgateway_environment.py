from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("configuration", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="paymentgatewayconfig",
            name="environment",
            field=models.CharField(
                choices=[("TEST", "Test"), ("LIVE", "Live")],
                default="TEST",
                max_length=10,
                verbose_name="Environment",
            ),
        ),
    ]
