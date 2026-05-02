from django.contrib import admin

from notifications.models import NotificationEvent, UserNotification


@admin.register(NotificationEvent)
class NotificationEventAdmin(admin.ModelAdmin):
    list_display = ("id", "module", "kind", "severity", "title", "actor", "created_at")
    list_filter = ("module", "kind", "severity", "created_at")
    search_fields = ("title", "message", "href", "kind", "module")
    autocomplete_fields = ("actor",)
    ordering = ("-created_at", "-id")


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "event", "is_read", "read_at")
    list_filter = ("is_read", "event__module", "event__severity")
    search_fields = ("user__username", "event__title", "event__message")
    autocomplete_fields = ("user", "event")
    ordering = ("-event__created_at", "-id")
