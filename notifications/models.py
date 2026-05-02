from django.contrib.auth.models import User
from django.db import models


class NotificationSeverity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


class NotificationEvent(models.Model):
    module = models.CharField(max_length=50, db_index=True)
    kind = models.CharField(max_length=100, db_index=True)
    severity = models.CharField(
        max_length=10,
        choices=NotificationSeverity.choices,
        default=NotificationSeverity.INFO,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True, default="")
    href = models.CharField(max_length=255, blank=True, default="")
    entity_type = models.CharField(max_length=50, blank=True, default="")
    entity_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_events",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["module", "created_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self):
        return f"{self.module}:{self.kind} — {self.title}"


class UserNotification(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="user_notifications",
    )
    event = models.ForeignKey(
        NotificationEvent,
        on_delete=models.CASCADE,
        related_name="user_notifications",
    )
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-event__created_at", "-id"]
        unique_together = [["user", "event"]]
        indexes = [
            models.Index(fields=["user", "is_read"]),
        ]

    def __str__(self):
        return f"{self.user.username} — {self.event.title}"
