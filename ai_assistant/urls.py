from django.urls import path

from ai_assistant.views import AssistantChatStreamView, AssistantChatView


urlpatterns = [
    path("chat/", AssistantChatView.as_view(), name="assistant-chat"),
    path("chat/stream/", AssistantChatStreamView.as_view(), name="assistant-chat-stream"),
]
