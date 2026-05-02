from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import UserNotification
from notifications.serializers import NotificationAlertSerializer, UserNotificationSerializer
from notifications.services import build_notification_summary, build_user_alerts


class NotificationSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(build_notification_summary(request.user))


class NotificationAlertsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        alerts = build_user_alerts(request.user)
        serializer = NotificationAlertSerializer(alerts, many=True)
        return Response(serializer.data)


class NotificationFeedView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserNotificationSerializer

    def get_queryset(self):
        return UserNotification.objects.filter(user=self.request.user).select_related("event", "event__actor")


class NotificationReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        notification = UserNotification.objects.filter(user=request.user, pk=pk).select_related("event", "event__actor").first()
        if not notification:
            return Response({"detail": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])

        return Response(UserNotificationSerializer(notification).data)


class NotificationReadAllView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        now = timezone.now()
        updated = UserNotification.objects.filter(user=request.user, is_read=False).update(is_read=True, read_at=now)
        return Response({"updated": updated})
