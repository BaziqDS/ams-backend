from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from ..models.inspection_model import InspectionCertificate, InspectionItem, InspectionStage, InspectionDocument
from ..models import Item, ItemBatch

class InspectionDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectionDocument
        fields = ('id', 'file', 'label', 'uploaded_at')

class InspectionItemSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_code = serializers.CharField(source='item.code', read_only=True)
    central_register_name = serializers.CharField(source='central_register.register_number', read_only=True)
    stock_register_name = serializers.CharField(source='stock_register.register_number', read_only=True)

    class Meta:
        model = InspectionItem
        fields = (
            'id', 'inspection_certificate', 'item', 'item_name', 'item_code',
            'item_description', 'item_specifications',
            'tendered_quantity', 'accepted_quantity', 'rejected_quantity',
            'unit_price', 'remarks',
            'stock_register', 'stock_register_name', 'stock_register_no', 
            'stock_register_page_no', 'stock_entry_date',
            'central_register', 'central_register_name', 'central_register_no', 
            'central_register_page_no', 'batch_number', 'expiry_date'
        )
        read_only_fields = ('inspection_certificate',)

class InspectionCertificateSerializer(serializers.ModelSerializer):
    items = InspectionItemSerializer(many=True)
    documents = InspectionDocumentSerializer(many=True, read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True)
    department_hierarchy_level = serializers.IntegerField(source='department.hierarchy_level', read_only=True)
    initiated_by_name = serializers.CharField(source='initiated_by.username', read_only=True)
    is_initiated = serializers.BooleanField(write_only=True, required=False, default=False)
    
    class Meta:
        model = InspectionCertificate
        fields = (
            'id', 'date', 'contract_no', 'contract_date',
            'contractor_name', 'contractor_address',
            'indenter', 'indent_no', 'department', 'department_name',
            'department_hierarchy_level',
            'date_of_delivery', 'delivery_type', 'remarks',
            'inspected_by', 'date_of_inspection',
            'consignee_name', 'consignee_designation',
            'stage', 'status', 'items', 'documents', 'is_initiated',
            'initiated_by', 'initiated_by_name', 'initiated_at',
            'stock_filled_by', 'stock_filled_at',
            'central_store_filled_by', 'central_store_filled_at',
            'finance_reviewed_at', 'finance_reviewed_by', 'finance_check_date',
            'rejected_by', 'rejected_at', 'rejection_reason', 'rejection_stage',
            'created_at', 'updated_at'
        )
        read_only_fields = (
            'stage', 'status', 'initiated_by', 'initiated_at',
            'stock_filled_by', 'stock_filled_at',
            'central_store_filled_by', 'central_store_filled_at',
            'finance_reviewed_at', 'finance_reviewed_by',
            'rejected_by', 'rejected_at', 'rejection_reason', 'rejection_stage',
            'created_at', 'updated_at'
        )

    def to_internal_value(self, data):
        # When using FormData (multipart/form-data), nested lists/dicts like 'items'
        # are often sent as JSON strings. We need to parse them before validation.
        if isinstance(data, dict) or hasattr(data, 'getlist'):
            # Create a mutable copy if it's a QueryDict
            if hasattr(data, 'copy'):
                data = data.copy()
            
            if 'items' in data and isinstance(data['items'], str):
                try:
                    import json
                    data['items'] = json.loads(data['items'])
                except (ValueError, TypeError):
                    pass
        
        return super().to_internal_value(data)

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        is_initiated = validated_data.pop('is_initiated', False)
        
        request = self.context.get('request')
        if request and request.user:
            validated_data['initiated_by'] = request.user
        
        if is_initiated:
            validated_data['status'] = 'IN_PROGRESS'
            validated_data['initiated_at'] = timezone.now()
            
            department = validated_data.get('department')
            if department and department.hierarchy_level == 0:
                validated_data['stage'] = InspectionStage.CENTRAL_REGISTER
            else:
                validated_data['stage'] = InspectionStage.STOCK_DETAILS
        else:
            validated_data['status'] = 'DRAFT'
            validated_data['stage'] = InspectionStage.DRAFT

        with transaction.atomic():
            certificate = InspectionCertificate.objects.create(**validated_data)
            for item_data in items_data:
                InspectionItem.objects.create(inspection_certificate=certificate, **item_data)
            
            # Handle document uploads from request.FILES
            if request and request.FILES:
                for file_key in request.FILES:
                    if file_key.startswith('documents['):
                        file = request.FILES[file_key]
                        InspectionDocument.objects.create(
                            inspection_certificate=certificate,
                            file=file,
                            label=file.name
                        )
                    # Support single file upload or differently named fields
                    elif file_key == 'file':
                        file = request.FILES[file_key]
                        InspectionDocument.objects.create(
                            inspection_certificate=certificate,
                            file=file,
                            label=file.name
                        )
        
        return certificate

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        is_initiated = validated_data.pop('is_initiated', False)
        
        request = self.context.get('request')
        
        if is_initiated and instance.stage == InspectionStage.DRAFT:
             instance.status = 'IN_PROGRESS'
             instance.initiated_at = timezone.now()
             if request and request.user:
                 instance.initiated_by = request.user
             
             if instance.department.hierarchy_level == 0:
                 instance.stage = InspectionStage.CENTRAL_REGISTER
             else:
                 instance.stage = InspectionStage.STOCK_DETAILS

        with transaction.atomic():
            # Update main fields
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            
            # Handle document uploads
            if request and request.FILES:
                for file_key in request.FILES:
                    if file_key.startswith('documents['):
                        file = request.FILES[file_key]
                        InspectionDocument.objects.create(
                            inspection_certificate=instance,
                            file=file,
                            label=file.name
                        )
                    elif file_key == 'file':
                        file = request.FILES[file_key]
                        InspectionDocument.objects.create(
                            inspection_certificate=instance,
                            file=file,
                            label=file.name
                        )

            # Update nested items if provided
            if items_data is not None:
                if instance.stage in [InspectionStage.DRAFT, InspectionStage.STOCK_DETAILS, InspectionStage.CENTRAL_REGISTER]:
                    existing_items = {item.id: item for item in instance.items.all()}
                    
                    new_item_ids = []
                    for item_data in items_data:
                        item_id = item_data.get('id')
                        if item_id and item_id in existing_items:
                            # Update existing
                            item_instance = existing_items[item_id]
                            for attr, value in item_data.items():
                                setattr(item_instance, attr, value)
                            item_instance.save()
                            new_item_ids.append(item_id)
                        else:
                            # Create new
                            new_item = InspectionItem.objects.create(inspection_certificate=instance, **item_data)
                            new_item_ids.append(new_item.id)
                    
                    # Delete removed
                    instance.items.exclude(id__in=new_item_ids).delete()
        
        return instance
