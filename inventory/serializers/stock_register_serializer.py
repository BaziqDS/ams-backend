from rest_framework import serializers
from ..models.stock_register_model import StockRegister


class StockRegisterSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = StockRegister
        fields = [
            'id', 'register_number', 'register_type', 'store', 'store_name',
            'is_active', 'created_at', 'updated_at', 'created_by_name'
        ]
        read_only_fields = ('created_at', 'updated_at', 'created_by')
