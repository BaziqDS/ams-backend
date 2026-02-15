from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LocationViewSet, CategoryViewSet, ItemViewSet, 
    StockRecordViewSet, StockEntryViewSet, PersonViewSet,
    StockAllocationViewSet, InspectionViewSet, ItemInstanceViewSet,
    ItemBatchViewSet, MovementHistoryViewSet, StockRegisterViewSet
)

router = DefaultRouter()
router.register(r'locations', LocationViewSet, basename='location')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'items', ItemViewSet, basename='item')
router.register(r'distribution', StockRecordViewSet, basename='distribution')
router.register(r'stock-entries', StockEntryViewSet, basename='stock-entry')
router.register(r'stock-allocations', StockAllocationViewSet, basename='stock-allocation')
router.register(r'inspections', InspectionViewSet, basename='inspection')
router.register(r'persons', PersonViewSet, basename='person')
router.register(r'item-instances', ItemInstanceViewSet, basename='item-instance')
router.register(r'item-batches', ItemBatchViewSet, basename='item-batch')
router.register(r'movement-history', MovementHistoryViewSet, basename='movement-history')
router.register(r'stock-registers', StockRegisterViewSet, basename='stock-register')




urlpatterns = [
    path('', include(router.urls)),
]
