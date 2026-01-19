from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)

class LocationType(models.TextChoices):
    DEPARTMENT = 'DEPARTMENT', 'Department'
    BUILDING = 'BUILDING', 'Building'
    STORE = 'STORE', 'Store'
    ROOM = 'ROOM', 'Room'
    LAB = 'LAB', 'Lab'
    JUNKYARD = 'JUNKYARD', 'Junkyard'
    OFFICE = 'OFFICE', 'Office'
    AV_HALL = 'AV_HALL', 'AV Hall'
    AUDITORIUM = 'AUDITORIUM', 'Auditorium'
    OTHER = 'OTHER', 'Other'

class Location(models.Model):
    name = models.CharField(max_length=255, unique=True, help_text="Location name must be unique")
    code = models.CharField(max_length=255, unique=True, blank=True, editable=False, help_text="Auto-generated if not provided")
    parent_location = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='child_locations'
    )
    location_type = models.CharField(
        max_length=20,
        choices=LocationType.choices
    )
    is_store = models.BooleanField(default=False)
    description = models.TextField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    in_charge = models.CharField(max_length=150, null=True, blank=True)
    contact_number = models.CharField(max_length=20, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    is_standalone = models.BooleanField(
        default=False,
        help_text="If true, this location can have sub-locations and will get a main store"
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_locations'
    )

    auto_created_store = models.OneToOneField(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parent_location_ref'
    )
    is_auto_created = models.BooleanField(default=False)
    is_main_store = models.BooleanField(
        default=False,
        help_text="Indicates if this is the main store for its parent standalone location"
    )

    hierarchy_level = models.PositiveIntegerField(default=0, editable=False)
    hierarchy_path = models.CharField(max_length=765, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        permissions = [
            ("manage_all_locations", "Can access all locations regardless of hierarchy"),
            ("create_standalone_location", "Can create standalone locations"),
            ("create_store_location", "Can create store locations"),
        ]
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['location_type']),
            models.Index(fields=['is_store']),
            models.Index(fields=['is_active']),
            models.Index(fields=['is_standalone']),
            models.Index(fields=['is_main_store']),
            models.Index(fields=['hierarchy_level']),
            models.Index(fields=['hierarchy_path']),
        ]

    def __str__(self):
        return f'{self.name} ({self.code})'

    @property
    def is_root_location(self):
        return self.parent_location is None

    def clean(self):
        super().clean()
        if self.code:
            existing = Location.objects.filter(code=self.code)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({'code': f"Location code '{self.code}' is already in use"})

        if not self.parent_location:
            existing_root = Location.objects.filter(parent_location__isnull=True)
            if self.pk: existing_root = existing_root.exclude(pk=self.pk)
            if existing_root.exists():
                raise ValidationError({'parent_location': "Only one root location is allowed."})

        if not self.parent_location and not self.is_standalone:
            raise ValidationError("Root location must be marked as standalone")

        if self.is_store and self.is_standalone:
            raise ValidationError("Store locations cannot be marked as standalone")

        if self.is_main_store and not self.is_store:
            raise ValidationError("Only store locations can be marked as main stores")

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_location_code()

        if self.parent_location:
            self.hierarchy_level = self.parent_location.hierarchy_level + 1
            self.hierarchy_path = f"{self.parent_location.hierarchy_path}/{self.code}"
        else:
            self.hierarchy_level = 0
            self.hierarchy_path = self.code

        super().save(*args, **kwargs)

    def generate_location_code(self):
        last_location = Location.objects.order_by('-id').first()
        next_seq = (last_location.id + 1) if last_location else 1
        type_prefix = {
            'DEPARTMENT': 'DEPT', 'BUILDING': 'BLDG', 'STORE': 'STR',
            'ROOM': 'ROOM', 'LAB': 'LAB', 'JUNKYARD': 'JUNK',
            'OFFICE': 'OFFC', 'AV_HALL': 'AVHL', 'AUDITORIUM': 'AUDI',
        }.get(self.location_type, 'LOC')
        
        while True:
            code = f"{type_prefix}-{next_seq:04d}"
            if not Location.objects.filter(code=code).exists():
                return code
            next_seq += 1

    def get_parent_standalone(self):
        if self.is_standalone: return self
        if not self.parent_location: return None
        current = self.parent_location
        while current:
            if current.is_standalone: return current
            current = current.parent_location
        return None

    def get_main_store(self):
        if self.is_store and self.is_main_store: return self
        if self.is_standalone and self.auto_created_store: return self.auto_created_store
        parent_standalone = self.get_parent_standalone()
        return parent_standalone.auto_created_store if parent_standalone else None

    def is_descendant_of(self, location):
        return self.hierarchy_path.startswith(f"{location.hierarchy_path}/")

    def get_descendants(self, include_self=False):
        if include_self:
            return Location.objects.filter(hierarchy_path__startswith=self.hierarchy_path, is_active=True)
        return Location.objects.filter(hierarchy_path__startswith=f"{self.hierarchy_path}/", is_active=True)

