from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LocationTagViewSet, LocationViewSet, CategoryViewSet, ItemViewSet, 
    StockRecordViewSet, StockEntryViewSet, PersonViewSet, EmployeeViewSet,
    StockCorrectionViewSet,
    StockAllocationViewSet, InspectionViewSet, ItemInstanceViewSet,
    ItemBatchViewSet, MovementHistoryViewSet, StockRegisterViewSet,
    AssetValueAdjustmentViewSet, DepreciationAssetClassViewSet,
    DepreciationPolicyViewSet, DepreciationRateVersionViewSet,
    DepreciationRunViewSet, FixedAssetRegisterEntryViewSet,
    MaintenanceMeterReadingViewSet, MaintenancePlanViewSet,
    MaintenanceWorkOrderViewSet,
)

router = DefaultRouter()
router.register(r'location-tags', LocationTagViewSet, basename='location-tag')
router.register(r'locations', LocationViewSet, basename='location')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'items', ItemViewSet, basename='item')
router.register(r'distribution', StockRecordViewSet, basename='distribution')
router.register(r'stock-entries', StockEntryViewSet, basename='stock-entry')
router.register(r'stock-corrections', StockCorrectionViewSet, basename='stock-correction')
router.register(r'stock-allocations', StockAllocationViewSet, basename='stock-allocation')
router.register(r'inspections', InspectionViewSet, basename='inspection')
router.register(r'employees', EmployeeViewSet, basename='employee')
router.register(r'persons', PersonViewSet, basename='person')
router.register(r'item-instances', ItemInstanceViewSet, basename='item-instance')
router.register(r'item-batches', ItemBatchViewSet, basename='item-batch')
router.register(r'movement-history', MovementHistoryViewSet, basename='movement-history')
router.register(r'stock-registers', StockRegisterViewSet, basename='stock-register')
router.register(r'depreciation/policies', DepreciationPolicyViewSet, basename='depreciation-policy')
router.register(r'depreciation/assets', FixedAssetRegisterEntryViewSet, basename='depreciation-asset')
router.register(r'depreciation/asset-classes', DepreciationAssetClassViewSet, basename='depreciation-asset-class')
router.register(r'depreciation/rates', DepreciationRateVersionViewSet, basename='depreciation-rate')
router.register(r'depreciation/runs', DepreciationRunViewSet, basename='depreciation-run')
router.register(r'depreciation/adjustments', AssetValueAdjustmentViewSet, basename='depreciation-adjustment')
router.register(r'maintenance/work-orders', MaintenanceWorkOrderViewSet, basename='maintenance-work-order')
router.register(r'maintenance/plans', MaintenancePlanViewSet, basename='maintenance-plan')
router.register(r'maintenance/meter-readings', MaintenanceMeterReadingViewSet, basename='maintenance-meter-reading')




urlpatterns = [
    path('', include(router.urls)),
]
