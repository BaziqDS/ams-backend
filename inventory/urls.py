from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LocationViewSet, CategoryViewSet, ItemViewSet, 
    StockRecordViewSet, StockEntryViewSet, PersonViewSet,
    StockCorrectionViewSet,
    StockAllocationViewSet, InspectionViewSet, ItemInstanceViewSet,
    ItemBatchViewSet, MovementHistoryViewSet, StockRegisterViewSet,
    AssetValueAdjustmentViewSet, DepreciationAssetClassViewSet,
    DepreciationPolicyViewSet, DepreciationRateVersionViewSet,
    DepreciationRunViewSet, FixedAssetRegisterEntryViewSet,
    ReportViewSet,
)

router = DefaultRouter()
router.register(r'locations', LocationViewSet, basename='location')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'items', ItemViewSet, basename='item')
router.register(r'distribution', StockRecordViewSet, basename='distribution')
router.register(r'stock-entries', StockEntryViewSet, basename='stock-entry')
router.register(r'stock-corrections', StockCorrectionViewSet, basename='stock-correction')
router.register(r'stock-allocations', StockAllocationViewSet, basename='stock-allocation')
router.register(r'inspections', InspectionViewSet, basename='inspection')
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




urlpatterns = [
    path(
        'reports/inventory-position/stores/',
        ReportViewSet.as_view({'get': 'stores'}),
        name='inventory-position-report-stores',
    ),
    path(
        'reports/inventory-position/pdf/',
        ReportViewSet.as_view({'get': 'inventory_position_pdf'}),
        name='inventory-position-report-pdf',
    ),
    path('', include(router.urls)),
]
