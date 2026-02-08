
from django.db import models
from django.contrib.auth.models import User
from .item_model import Item
from .batch_model import ItemBatch
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
    batch = models.ForeignKey(ItemBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='instances')
    
    serial_number = models.CharField(max_length=100, unique=True, null=True, blank=True)
    qr_code = models.CharField(max_length=255, unique=True, null=True, blank=True)
    qr_code_image = models.ImageField(upload_to='qr_codes/', null=True, blank=True)
    
    current_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='instances')
    status = models.CharField(max_length=20, choices=InstanceStatus.choices, default=InstanceStatus.AVAILABLE, db_index=True)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.item.name} ({self.serial_number or self.id})"

    def generate_qr_code_image(self):
        """
        Generates a QR code image linking to the frontend detail page.
        """
        import qrcode
        from io import BytesIO
        from django.core.files import File
        from django.conf import settings
        
        # Construct the URL
        # Format: /items/:id/instances/:locationId/:instanceId
        base_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        url = f"{base_url}/items/{self.item.id}/instances/{self.current_location.id}/{self.id}"
        
        # Generate QR
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
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
