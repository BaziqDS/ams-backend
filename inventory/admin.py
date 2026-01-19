from django.contrib import admin
from .models.location_model import Location
from .models.category_model import Category, CategoryRateHistory

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
