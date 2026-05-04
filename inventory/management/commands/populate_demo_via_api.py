from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from inventory.demo_population import DEFAULT_DEMO_PASSWORD, PopulateConfig, PopulationError, populate_demo_data


class Command(BaseCommand):
    help = "Populate demo/showcase data through the existing API POST/PATCH endpoints."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Existing superuser username to execute the API population as.")
        parser.add_argument("--tag", default="DEMO", help="Human-readable tag added to seeded records.")
        parser.add_argument("--role-count", type=int, default=20)
        parser.add_argument("--standalone-units", type=int, default=20)
        parser.add_argument("--child-locations-per-unit", type=int, default=2)
        parser.add_argument("--internal-stores-per-unit", type=int, default=1)
        parser.add_argument("--fixed-asset-parent-count", type=int, default=20)
        parser.add_argument("--consumable-parent-count", type=int, default=6)
        parser.add_argument("--perishable-parent-count", type=int, default=4)
        parser.add_argument("--item-count", type=int, default=40)
        parser.add_argument("--person-count", type=int, default=20)
        parser.add_argument("--user-count", type=int, default=20)
        parser.add_argument("--completed-root-inspections", type=int, default=20)
        parser.add_argument("--completed-department-inspections", type=int, default=20)
        parser.add_argument("--finance-review-inspections", type=int, default=6)
        parser.add_argument("--central-register-inspections", type=int, default=6)
        parser.add_argument("--draft-inspections", type=int, default=6)
        parser.add_argument("--manual-person-allocations", type=int, default=10)
        parser.add_argument("--manual-location-allocations", type=int, default=10)
        parser.add_argument("--manual-returns", type=int, default=10)
        parser.add_argument("--depreciation-run-count", type=int, default=20)
        parser.add_argument("--asset-adjustments", type=int, default=20)
        parser.add_argument("--user-password", default=DEFAULT_DEMO_PASSWORD, help="Password assigned to seeded demo users.")

    def handle(self, *args, **options):
        username = options.get("username")
        if username:
            user = User.objects.filter(username=username, is_superuser=True).first()
            if not user:
                raise CommandError(f"No superuser found with username '{username}'.")
        else:
            user = User.objects.filter(is_superuser=True).order_by("id").first()
            if not user:
                raise CommandError("No superuser exists. Create one first, then re-run this command.")

        config = PopulateConfig(
            tag=options["tag"],
            role_count=options["role_count"],
            standalone_units=options["standalone_units"],
            child_locations_per_unit=options["child_locations_per_unit"],
            internal_stores_per_unit=options["internal_stores_per_unit"],
            fixed_asset_parent_count=options["fixed_asset_parent_count"],
            consumable_parent_count=options["consumable_parent_count"],
            perishable_parent_count=options["perishable_parent_count"],
            item_count=options["item_count"],
            person_count=options["person_count"],
            user_count=options["user_count"],
            completed_root_inspections=options["completed_root_inspections"],
            completed_department_inspections=options["completed_department_inspections"],
            finance_review_inspections=options["finance_review_inspections"],
            central_register_inspections=options["central_register_inspections"],
            draft_inspections=options["draft_inspections"],
            manual_person_allocations=options["manual_person_allocations"],
            manual_location_allocations=options["manual_location_allocations"],
            manual_returns=options["manual_returns"],
            depreciation_run_count=options["depreciation_run_count"],
            asset_adjustments=options["asset_adjustments"],
            user_password=options["user_password"],
        )

        self.stdout.write(self.style.NOTICE(f"Seeding demo data via API as superuser '{user.username}'..."))
        self.stdout.write(f"Tag: {config.tag}")

        try:
            summary = populate_demo_data(user, config)
        except PopulationError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Demo data population completed."))
        self.stdout.write(f"Seeded user password: {summary['seeded_user_password']}")
        self.stdout.write("Summary:")
        for key, value in summary.items():
            if key in {"tag", "seeded_user_password"}:
                continue
            self.stdout.write(f"  - {key.replace('_', ' ')}: {value}")
