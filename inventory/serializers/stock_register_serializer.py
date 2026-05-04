from django.db import models
from rest_framework import serializers
from ..models.stock_register_model import StockRegister
from ..models.location_model import Location


class StockRegisterSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    closed_by_name = serializers.CharField(source='closed_by.username', read_only=True)
    reopened_by_name = serializers.CharField(source='reopened_by.username', read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            self.fields['store'].queryset = Location.objects.none()
            return

        if request.user.is_superuser:
            self.fields['store'].queryset = Location.objects.filter(is_store=True, is_active=True)
            return

        if not hasattr(request.user, 'profile'):
            self.fields['store'].queryset = Location.objects.none()
            return

        creatable_stores = request.user.profile.get_creatable_stock_register_stores()
        current_store_id = getattr(self.instance, 'store_id', None)
        if current_store_id:
            creatable_stores = Location.objects.filter(
                models.Q(id__in=creatable_stores.values_list('id', flat=True))
                | models.Q(id=current_store_id),
                is_store=True,
                is_active=True,
            ).distinct()
        self.fields['store'].queryset = creatable_stores.filter(is_store=True, is_active=True)

    class Meta:
        model = StockRegister
        fields = [
            'id', 'register_number', 'register_type', 'store', 'store_name',
            'is_active', 'closed_at', 'closed_by', 'closed_by_name', 'closed_reason',
            'reopened_at', 'reopened_by', 'reopened_by_name', 'reopened_reason',
            'created_at', 'updated_at', 'created_by_name'
        ]
        read_only_fields = (
            'created_at', 'updated_at', 'created_by',
            'closed_at', 'closed_by', 'reopened_at', 'reopened_by',
        )
