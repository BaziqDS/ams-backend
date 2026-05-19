from django.core.management.base import BaseCommand

from inventory.models import ItemInstance


class Command(BaseCommand):
    help = "Regenerate item-instance QR images using the current asset identification payload."

    def add_arguments(self, parser):
        parser.add_argument(
            "--instance-id",
            type=int,
            action="append",
            dest="instance_ids",
            help="Regenerate one item instance. Can be provided multiple times.",
        )

    def handle(self, *args, **options):
        queryset = ItemInstance.objects.select_related(
            "item__category__parent_category",
            "current_location__parent_location",
        ).order_by("id")

        instance_ids = options.get("instance_ids")
        if instance_ids:
            queryset = queryset.filter(id__in=instance_ids)

        count = 0
        for item_instance in queryset.iterator():
            item_instance.generate_qr_code_image()
            item_instance.save(update_fields=["qr_code_image"])
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Regenerated {count} item-instance QR code image(s)."))
