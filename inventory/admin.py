from django.contrib import admin
from .models.location_model import Location
from .models.category_model import Category, CategoryRateHistory
from .models.item_model import Item
from .models.batch_model import ItemBatch
from .models.instance_model import ItemInstance
from .models.stock_record_model import StockRecord
from .models.stockentry_model import StockEntry, StockEntryItem
from .models.person_model import Person

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'location_type', 'is_store', 'is_standalone', 'is_main_store', 'is_active')
    list_filter = ('location_type', 'is_store', 'is_standalone', 'is_main_store', 'is_active')
    search_fields = ('name', 'code')
    ordering = ('name',)

class CategoryRateHistoryInline(admin.TabularInline):
    model = CategoryRateHistory
    extra = 0
    readonly_fields = ('changed_at', 'rate', 'changed_by', 'notes')
    can_delete = False

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category_type', 'tracking_type', 'is_active')
    list_filter = ('category_type', 'tracking_type', 'is_active')
    search_fields = ('name', 'code')
    ordering = ('name',)
    inlines = [CategoryRateHistoryInline]

@admin.register(CategoryRateHistory)
class CategoryRateHistoryAdmin(admin.ModelAdmin):
    list_display = ('category', 'rate', 'changed_at', 'changed_by')
    list_filter = ('category', 'changed_at')
    date_hierarchy = 'changed_at'

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'total_quantity', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'code')

@admin.register(ItemBatch)
class ItemBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_number', 'item', 'manufactured_date', 'expiry_date', 'is_active')
    list_filter = ('item', 'is_active')
    search_fields = ('batch_number',)

@admin.register(ItemInstance)
class ItemInstanceAdmin(admin.ModelAdmin):
    list_display = ('serial_number', 'item', 'current_location', 'status')
    list_filter = ('item', 'status', 'current_location')
    search_fields = ('serial_number', 'qr_code')

@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ('name', 'employee_id', 'department', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'employee_id')

class StockEntryItemInline(admin.TabularInline):
    model = StockEntryItem
    extra = 1

@admin.register(StockRecord)
class StockRecordAdmin(admin.ModelAdmin):
    list_display = ('item', 'batch', 'location', 'quantity', 'last_updated')
    list_filter = ('item', 'location')

@admin.register(StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = ('entry_number', 'entry_type', 'from_location', 'to_location', 'issued_to', 'status', 'entry_date')
    list_filter = ('entry_type', 'status', 'entry_date')
    search_fields = ('entry_number', 'remarks')
    inlines = [StockEntryItemInline]

