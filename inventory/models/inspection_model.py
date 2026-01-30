from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

class InspectionStage(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    STOCK_DETAILS = 'STOCK_DETAILS', 'Stock Details (Stage 2)'
    CENTRAL_REGISTER = 'CENTRAL_REGISTER', 'Central Register (Stage 3)'
    FINANCE_REVIEW = 'FINANCE_REVIEW', 'Finance Review (Stage 4)'
    COMPLETED = 'COMPLETED', 'Completed'
    REJECTED = 'REJECTED', 'Rejected'

class InspectionCertificate(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
        ('REJECTED', 'Rejected'),
    ]

    date = models.DateField(default=timezone.now)
    contract_no = models.CharField(max_length=100, unique=True)
    contract_date = models.DateField(null=True, blank=True)
    contractor_name = models.CharField(max_length=255)
    contractor_address = models.TextField(blank=True, null=True)
    indenter = models.CharField(max_length=150)
    indent_no = models.CharField(max_length=100)

    department = models.ForeignKey(
        'Location',
        on_delete=models.PROTECT,
        related_name='inspections',
        limit_choices_to={'is_standalone': True},
    )

    date_of_delivery = models.DateField(null=True, blank=True)
    delivery_type = models.CharField(
        max_length=20,
        choices=[('PART', 'Part'), ('FULL', 'Full')],
        default='FULL'
    )
    remarks = models.TextField(blank=True, null=True)

    inspected_by = models.CharField(max_length=150, blank=True, null=True)
    date_of_inspection = models.DateField(null=True, blank=True)
    consignee_name = models.CharField(max_length=150, blank=True, null=True)
    consignee_designation = models.CharField(max_length=150, blank=True, null=True)

    stage = models.CharField(
        max_length=20,
        choices=InspectionStage.choices,
        default=InspectionStage.DRAFT
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    # Audit tracking
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='initiated_inspections')
    initiated_at = models.DateTimeField(auto_now_add=True)

    stock_filled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_filled_inspections')
    stock_filled_at = models.DateTimeField(null=True, blank=True)

    central_store_filled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='central_filled_inspections')
    central_store_filled_at = models.DateTimeField(null=True, blank=True)
    
    finance_reviewed_at = models.DateTimeField(null=True, blank=True)
    finance_reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='finance_reviewed_inspections')
    finance_check_date = models.DateField(null=True, blank=True)

    rejected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rejected_inspections')
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    rejection_stage = models.CharField(max_length=20, choices=InspectionStage.choices, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"IC-{self.contract_no} ({self.stage})"

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ("initiate_inspection", "Can initiate inspection"),
            ("fill_stock_details", "Can fill stock details (Stage 2)"),
            ("fill_central_register", "Can fill central register (Stage 3)"),
            ("review_finance", "Can perform finance review (Stage 4)"),
        ]

class InspectionItem(models.Model):
    inspection_certificate = models.ForeignKey(
        InspectionCertificate,
        on_delete=models.CASCADE,
        related_name='items'
    )
    
    # Selected system item (nullable until Stage 3)
    item = models.ForeignKey(
        'Item',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='inspection_items'
    )

    item_description = models.TextField()
    item_specifications = models.TextField(blank=True, null=True)
    
    tendered_quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    accepted_quantity = models.PositiveIntegerField(default=0)
    rejected_quantity = models.PositiveIntegerField(default=0)
    
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    remarks = models.TextField(blank=True, null=True)

    # Stage 2: Stock Register Details
    stock_register_no = models.CharField(max_length=100, blank=True, null=True)
    stock_register_page_no = models.CharField(max_length=50, blank=True, null=True)
    stock_entry_date = models.DateField(null=True, blank=True)

    # Stage 3: Central Register Details
    central_register_no = models.CharField(max_length=100, blank=True, null=True)
    central_register_page_no = models.CharField(max_length=50, blank=True, null=True)

    # Tracking info (set at Stage 3 if item is linked)
    batch_number = models.CharField(max_length=100, blank=True, null=True)
    expiry_date = models.DateField(null=True, blank=True)

    def clean(self):
        if (self.accepted_quantity + self.rejected_quantity) > self.tendered_quantity:
            raise ValidationError("Accepted + Rejected quantity cannot exceed Tendered quantity.")

    def __str__(self):
        return f"{self.item_description[:50]} ({self.inspection_certificate.contract_no})"
