from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserProfileViewSet, UserViewSet, AvailablePermissionsView

router = DefaultRouter()
router.register(r'profiles', UserProfileViewSet)
router.register(r'management', UserViewSet, basename='user-management')

urlpatterns = [
    path('available-permissions/', AvailablePermissionsView.as_view(), name='available-permissions'),
    path('', include(router.urls)),
]
