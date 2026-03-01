"""
URL configuration for ams project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from ams.auth_views import CookieLoginView, CookieRefreshView, CookieLogoutView

urlpatterns = [
    path('admin/', admin.site.urls),
    # Cookie-based JWT auth (httpOnly — XSS-safe)
    path('auth/cookie/login/', CookieLoginView.as_view(), name='cookie-login'),
    path('auth/cookie/refresh/', CookieRefreshView.as_view(), name='cookie-refresh'),
    path('auth/cookie/logout/', CookieLogoutView.as_view(), name='cookie-logout'),
    # Djoser endpoints (user management, /auth/users/me/, etc.)
    path('auth/', include('djoser.urls')),
    path('auth/', include('djoser.urls.jwt')),
    
    # App endpoints
    path('api/users/', include('user_management.urls')),
    path('api/inventory/', include('inventory.urls')),
    path('silk/', include('silk.urls', namespace='silk')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
