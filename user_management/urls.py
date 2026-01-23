from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserProfileViewSet, UserViewSet, GroupViewSet, AvailablePermissionsView

router = DefaultRouter()
router.register(r'profiles', UserProfileViewSet)
router.register(r'management', UserViewSet, basename='user-management')
router.register(r'groups', GroupViewSet)

urlpatterns = [
    path('available-permissions/', AvailablePermissionsView.as_view(), name='available-permissions'),
    path('', include(router.urls)),
]
