from django.urls import path

from notifications.views import (
    NotificationAlertsView,
    NotificationFeedView,
    NotificationReadAllView,
    NotificationReadView,
    NotificationSummaryView,
)

urlpatterns = [
    path("summary/", NotificationSummaryView.as_view(), name="notification-summary"),
    path("alerts/", NotificationAlertsView.as_view(), name="notification-alerts"),
    path("feed/", NotificationFeedView.as_view(), name="notification-feed"),
    path("feed/read-all/", NotificationReadAllView.as_view(), name="notification-read-all"),
    path("feed/<int:pk>/read/", NotificationReadView.as_view(), name="notification-read"),
]
