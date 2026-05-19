from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0053_assetvalueadjustment_assetadjust_asset_date_idx_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="inspectioncertificate",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("initiate_inspection", "Can initiate inspection"),
                    ("fill_stock_details", "Can fill stock details (Stage 2)"),
                    ("fill_central_register", "Can fill central register (Stage 3)"),
                    ("review_finance", "Can perform finance review (Stage 4)"),
                    ("view_all_inspections", "Can view all inspection certificates university-wide"),
                ],
            },
        ),
    ]
