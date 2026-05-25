from django.core.management.base import BaseCommand, CommandError

from inventory.services.stock_reconciliation_service import StockReconciliationService


class Command(BaseCommand):
    help = "Detect and optionally repair StockRecord summary mismatches and invalid pending reservations."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply detected StockRecord counter repairs and void invalid pending quantity issues.")
        parser.add_argument("--dry-run", action="store_true", help="Report mismatches without changing data. This is the default.")
        parser.add_argument("--item", type=int, help="Limit reconciliation to one item id.")
        parser.add_argument("--location", type=int, help="Limit reconciliation to one location id.")
        parser.add_argument("--reason", default="", help="Audit reason stored with the reconciliation run.")
        parser.add_argument(
            "--void-duplicate-pending-entries",
            action="store_true",
            help="When used with --apply, void later pending issue entries that reserve the same individual instance.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        dry_run = options["dry_run"]
        if apply and dry_run:
            raise CommandError("Use either --apply or --dry-run, not both.")

        run = StockReconciliationService.run(
            item_id=options.get("item"),
            location_id=options.get("location"),
            apply=apply,
            reason=options.get("reason") or "",
            void_duplicate_pending_entries=options["void_duplicate_pending_entries"],
        )
        findings = list(run.findings.select_related('stock_record', 'item', 'location').all())

        if not findings:
            self.stdout.write(self.style.SUCCESS("No stock reconciliation mismatches found."))
            return

        mode = "APPLIED" if apply else "DRY RUN"
        self.stdout.write(f"{mode}: {len(findings)} stock reconciliation mismatch(es) found.")
        for finding in findings:
            self.stdout.write(f"{finding.finding_type}: {finding.message}")
            if finding.stock_record:
                self.stdout.write(
                    f"StockRecord {finding.stock_record_id} ({finding.item.name} @ {finding.location.name})"
                )
            if 'quantity' in finding.before or 'quantity' in finding.after:
                before = finding.before.get('quantity')
                after = finding.after.get('quantity')
                if before != after:
                    self.stdout.write(f"  quantity: {before} -> {after}")
            if 'in_transit_quantity' in finding.before or 'in_transit_quantity' in finding.after:
                before = finding.before.get('in_transit_quantity')
                after = finding.after.get('in_transit_quantity')
                if before != after:
                    self.stdout.write(f"  in_transit_quantity: {before} -> {after}")
            if 'allocated_quantity' in finding.before or 'allocated_quantity' in finding.after:
                before = finding.before.get('allocated_quantity')
                after = finding.after.get('allocated_quantity')
                if before != after:
                    self.stdout.write(f"  allocated_quantity: {before} -> {after}")
            if finding.applied:
                self.stdout.write("  applied: yes")

        if apply:
            self.stdout.write(self.style.SUCCESS(f"Stock reconciliation run {run.id} applied {run.applied_count} repair(s)."))
        else:
            self.stdout.write(f"Run with --apply to write repairable findings. Audit run id: {run.id}")
