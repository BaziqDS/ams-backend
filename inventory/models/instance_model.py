
from django.db import models
from django.contrib.auth.models import User
from .item_model import Item
from .location_model import Location

class InstanceStatus(models.TextChoices):
    AVAILABLE = 'AVAILABLE', 'Available'
    IN_TRANSIT = 'IN_TRANSIT', 'In Transit'
    ISSUED = 'ISSUED', 'Issued'
    ALLOCATED = 'ALLOCATED', 'Allocated'
    IN_USE = 'IN_USE', 'In Use'
    MAINTENANCE = 'MAINTENANCE', 'In Maintenance'
    JUNK = 'JUNK', 'Junked/Disposed'
    LOST = 'LOST', 'Lost'

class ItemInstance(models.Model):
    """
    Individual tracked unit of an Item.
    """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='instances')

    # Link to inspection certificate - tracks which IC this instance came from
    inspection_certificate = models.ForeignKey(
        'InspectionCertificate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='item_instances'
    )
    
    # Serial number - NULL by default, should be assigned later by store manager
    
    serial_number = models.CharField(max_length=100, unique=True, null=True, blank=True)
    qr_code = models.CharField(max_length=255, unique=True, null=True, blank=True)
    qr_code_image = models.ImageField(upload_to='qr_codes/', null=True, blank=True)
    
    current_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='instances')
    authority_store = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='owned_instances',
        limit_choices_to={'is_store': True},
        help_text="Store that currently owns this instance. Allocations keep this store while current location may move.",
    )
    status = models.CharField(max_length=20, choices=InstanceStatus.choices, default=InstanceStatus.AVAILABLE, db_index=True)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        permissions = [
            ("change_item_instance", "Can change item instance details"),
        ]

    def __str__(self):
        return f"{self.item.name} ({self.serial_number or self.id})"

    def _clean_qr_value(self, value, fallback="Not Recorded"):
        if value is None:
            return fallback
        text = str(value).strip()
        return text if text else fallback

    def get_qr_classification(self):
        category = self.item.category
        if category.parent_category:
            return f"{category.parent_category.name} / {category.name}"
        return category.name

    def get_latest_active_allocation(self):
        from .allocation_model import AllocationStatus, StockAllocation

        return StockAllocation.objects.filter(
            item=self.item,
            batch__isnull=True,
            status=AllocationStatus.ALLOCATED,
            stock_entry__items__instances=self,
        ).select_related(
            'allocated_to_person',
            'allocated_to_location',
            'source_location',
        ).order_by('-allocated_at').first()

    def get_qr_status_label(self):
        status_labels = {
            InstanceStatus.AVAILABLE: "In Store" if self.current_location.is_store else "Available",
            InstanceStatus.IN_TRANSIT: "In Transit",
            InstanceStatus.ISSUED: "Issued",
            InstanceStatus.ALLOCATED: "Allocated",
            InstanceStatus.IN_USE: "In Use",
            InstanceStatus.MAINTENANCE: "Under Maintenance",
            InstanceStatus.JUNK: "Disposed",
            InstanceStatus.LOST: "Lost",
        }
        return status_labels.get(self.status, self.get_status_display())

    def get_qr_placement(self):
        if self.status == InstanceStatus.IN_TRANSIT:
            latest_pending = self.stock_entry_items.filter(
                stock_entry__status='PENDING_ACK',
                stock_entry__to_location__isnull=False,
            ).select_related('stock_entry__to_location').order_by('-stock_entry__entry_date').first()
            if latest_pending and latest_pending.stock_entry.to_location:
                return f"Transfer in Progress to {latest_pending.stock_entry.to_location.name}"
            return "Transfer in Progress"

        if self.status == InstanceStatus.JUNK:
            return "Not Applicable"

        return self._clean_qr_value(getattr(self.current_location, 'name', None))

    def get_qr_custodian(self):
        if self.status in {InstanceStatus.JUNK, InstanceStatus.LOST}:
            return "Not Applicable"
        if self.status == InstanceStatus.IN_TRANSIT:
            return "Pending Receipt"

        allocation = self.get_latest_active_allocation() if self.status == InstanceStatus.ALLOCATED else None
        if allocation:
            if allocation.allocated_to_person:
                return self._clean_qr_value(allocation.allocated_to_person.name)
            if allocation.allocated_to_location:
                return self._clean_qr_value(allocation.allocated_to_location.name)

        return self._clean_qr_value(getattr(self.current_location, 'name', None))

    def get_qr_owning_store(self):
        if self.authority_store:
            return self._clean_qr_value(self.authority_store.name)

        allocation = self.get_latest_active_allocation() if self.status == InstanceStatus.ALLOCATED else None
        if allocation and allocation.source_location:
            return self._clean_qr_value(allocation.source_location.name)
        if self.current_location.is_store:
            return self._clean_qr_value(self.current_location.name)

        containing_store = self.current_location.get_containing_main_store()
        if containing_store:
            return self._clean_qr_value(containing_store.name)

        return "Not Recorded"

    def build_qr_payload(self):
        """
        Builds the plain-text asset identification payload encoded in the QR image.
        The QR intentionally does not link to the authenticated web application.
        """
        identifier = self._clean_qr_value(self.qr_code or self.serial_number or f"Instance #{self.pk}")
        return "\n".join([
            "NED UNIVERSITY - ASSET IDENTIFICATION",
            "",
            f"Asset Instance No.: {identifier}",
            f"Classification: {self.get_qr_classification()}",
            f"Item Name: {self.item.name}",
            "",
            f"Operational Status: {self.get_qr_status_label()}",
            f"Current Placement: {self.get_qr_placement()}",
            f"Custodian: {self.get_qr_custodian()}",
            f"Owning Store: {self.get_qr_owning_store()}",
        ])

    def generate_qr_code_image(self):
        """
        Generates a QR code image containing a plain-text asset identification summary.
        """
        import qrcode
        from io import BytesIO
        from django.core.files import File
        
        # Generate QR
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(self.build_qr_payload())
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to BytesIO
        blob = BytesIO()
        img.save(blob, 'PNG')
        
        # Save to field
        fname = f"qr-{self.id}.png"
        self.qr_code_image.save(fname, File(blob), save=False)

    def save(self, *args, **kwargs):
        # 1. Generate QR string identifier if missing
        if not self.qr_code:
            import uuid
            self.qr_code = f"AMS-INST-{uuid.uuid4().hex[:12].upper()}"
        
        # 2. First save to ensure we have an ID for the image filename/URL
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # 3. Generate the actual QR image if it's new or location changed
        # For now, we'll just generate it if it doesn't exist.
        if is_new or not self.qr_code_image:
            self.generate_qr_code_image()
            super().save(update_fields=['qr_code_image'])
