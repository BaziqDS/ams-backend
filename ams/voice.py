from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.views import APIView

from ai_assistant.views import AssistantEnabled
from rest_framework.permissions import IsAuthenticated
from user_management.models import VoiceUsage


class VoicePermitView(APIView):
    permission_classes = [IsAuthenticated, AssistantEnabled]

    def post(self, request):
        now = timezone.now()
        with transaction.atomic():
            usage, _ = VoiceUsage.objects.get_or_create(
                user=request.user, defaults={'day': now.date(), 'minute_started_at': now},
            )
            usage = VoiceUsage.objects.select_for_update().get(pk=usage.pk)
            if usage.day != now.date():
                usage.day, usage.daily_count = now.date(), 0
            if now - usage.minute_started_at >= timedelta(minutes=1):
                usage.minute_started_at, usage.minute_count = now, 0
            if usage.daily_count >= settings.VOICE_DAILY_LIMIT:
                raise Throttled(detail='Daily voice quota reached.')
            if usage.minute_count >= settings.VOICE_MINUTE_LIMIT:
                raise Throttled(wait=60, detail='Voice request rate exceeded.')
            usage.daily_count += 1
            usage.minute_count += 1
            usage.save()
        return Response({'allowed': True})
