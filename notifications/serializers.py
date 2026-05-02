from rest_framework import serializers

from notifications.models import UserNotification


class UserNotificationSerializer(serializers.ModelSerializer):
    event_id = serializers.IntegerField(read_only=True)
    module = serializers.CharField(source="event.module", read_only=True)
    kind = serializers.CharField(source="event.kind", read_only=True)
    severity = serializers.CharField(source="event.severity", read_only=True)
    title = serializers.CharField(source="event.title", read_only=True)
    message = serializers.CharField(source="event.message", read_only=True)
    href = serializers.CharField(source="event.href", read_only=True)
    entity_type = serializers.CharField(source="event.entity_type", read_only=True)
    entity_id = serializers.IntegerField(source="event.entity_id", allow_null=True, read_only=True)
    actor_id = serializers.IntegerField(source="event.actor_id", allow_null=True, read_only=True)
    actor_name = serializers.CharField(source="event.actor.username", allow_null=True, read_only=True)
    metadata = serializers.JSONField(source="event.metadata", read_only=True)
    created_at = serializers.DateTimeField(source="event.created_at", read_only=True)

    class Meta:
        model = UserNotification
        fields = (
            "id",
            "event_id",
            "module",
            "kind",
            "severity",
            "title",
            "message",
            "href",
            "entity_type",
            "entity_id",
            "actor_id",
            "actor_name",
            "metadata",
            "created_at",
            "is_read",
            "read_at",
        )


class NotificationAlertSerializer(serializers.Serializer):
    key = serializers.CharField()
    module = serializers.CharField()
    severity = serializers.CharField()
    title = serializers.CharField()
    message = serializers.CharField()
    href = serializers.CharField(allow_blank=True)
    count = serializers.IntegerField(min_value=1)
    meta = serializers.JSONField(required=False)
