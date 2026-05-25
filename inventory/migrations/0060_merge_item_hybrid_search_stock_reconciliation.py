from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0057_item_hybrid_search"),
        ("inventory", "0059_stock_reconciliation_audit_voided_stockentry"),
    ]

    operations = []
