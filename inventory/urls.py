from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LocationViewSet, CategoryViewSet, ItemViewSet
from .views.distribution_views import StockRecordViewSet
from .views.stockentry_views import StockEntryViewSet, PersonViewSet

router = DefaultRouter()
router.register(r'locations', LocationViewSet, basename='location')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'items', ItemViewSet, basename='item')
router.register(r'distribution', StockRecordViewSet, basename='distribution')
router.register(r'stock-entries', StockEntryViewSet, basename='stock-entry')
router.register(r'persons', PersonViewSet, basename='person')


urlpatterns = [
    path('', include(router.urls)),
]
