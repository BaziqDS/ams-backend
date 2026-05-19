from django.http import StreamingHttpResponse
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_assistant.service import AssistantConfigurationError, InventoryAssistantService


class ConversationTurnSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField(allow_blank=False, trim_whitespace=True)


class AssistantChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(allow_blank=False, trim_whitespace=True)
    history = ConversationTurnSerializer(many=True, required=False, default=list)


class AssistantChatView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AssistantChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            service = InventoryAssistantService()
            response = service.chat(
                message=serializer.validated_data["message"],
                history=serializer.validated_data.get("history", []),
            )
        except AssistantConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(
            {
                "mode": response.mode,
                "text": response.text,
                "openui_code": response.openui_code,
                "sql_answer": response.sql_answer,
            }
        )


class AssistantChatStreamView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AssistantChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def event_stream():
            try:
                service = InventoryAssistantService()
                for event in service.stream_chat_events(
                    message=serializer.validated_data["message"],
                    history=serializer.validated_data.get("history", []),
                ):
                    yield service.encode_stream_event(event)
            except AssistantConfigurationError as exc:
                yield InventoryAssistantService.encode_stream_event({"type": "error", "message": str(exc)})

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response
