import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0058_alter_location_options"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="stockentry",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("PENDING_ACK", "Pending Acknowledgment"),
                    ("COMPLETED", "Completed"),
                    ("REJECTED", "Rejected"),
                    ("CANCELLED", "Cancelled"),
                    ("VOIDED", "Voided"),
                ],
                db_index=True,
                default="DRAFT",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="void_reason",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="voided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="voided_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="voided_entries",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="StockReconciliationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "mode",
                    models.CharField(
                        choices=[("DRY_RUN", "Dry Run"), ("APPLY", "Apply")],
                        db_index=True,
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("COMPLETED", "Completed"), ("FAILED", "Failed")],
                        db_index=True,
                        default="COMPLETED",
                        max_length=20,
                    ),
                ),
                ("reason", models.TextField(blank=True, default="")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("findings_count", models.PositiveIntegerField(default=0)),
                ("applied_count", models.PositiveIntegerField(default=0)),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_reconciliation_runs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "scope_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reconciliation_runs",
                        to="inventory.item",
                    ),
                ),
                (
                    "scope_location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reconciliation_runs",
                        to="inventory.location",
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at"],
            },
        ),
        migrations.CreateModel(
            name="StockReconciliationFinding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "finding_type",
                    models.CharField(
                        choices=[
                            ("STOCK_RECORD_SUMMARY_MISMATCH", "Stock record summary mismatch"),
                            ("DUPLICATE_ACTIVE_INSTANCE_RESERVATION", "Duplicate active instance reservation"),
                            ("INDIVIDUAL_MOVEMENT_INSTANCE_MISMATCH", "Individual movement instance mismatch"),
                            ("QUANTITY_PENDING_OVER_ISSUE", "Quantity pending issue exceeds source stock"),
                        ],
                        db_index=True,
                        max_length=60,
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[("INFO", "Info"), ("WARNING", "Warning"), ("CRITICAL", "Critical")],
                        db_index=True,
                        default="WARNING",
                        max_length=20,
                    ),
                ),
                ("repairable", models.BooleanField(default=False)),
                ("applied", models.BooleanField(default=False)),
                ("message", models.TextField()),
                ("before", models.JSONField(blank=True, default=dict)),
                ("after", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reconciliation_findings",
                        to="inventory.item",
                    ),
                ),
                (
                    "item_instance",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reconciliation_findings",
                        to="inventory.iteminstance",
                    ),
                ),
                (
                    "location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reconciliation_findings",
                        to="inventory.location",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="findings",
                        to="inventory.stockreconciliationrun",
                    ),
                ),
                (
                    "stock_entry",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reconciliation_findings",
                        to="inventory.stockentry",
                    ),
                ),
                (
                    "stock_entry_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reconciliation_findings",
                        to="inventory.stockentryitem",
                    ),
                ),
                (
                    "stock_record",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reconciliation_findings",
                        to="inventory.stockrecord",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
