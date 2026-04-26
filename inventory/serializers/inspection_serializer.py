from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from ..models.inspection_model import InspectionCertificate, InspectionItem, InspectionStage, InspectionDocument
from ..models.stockentry_model import StockEntry
from ..models import Item, ItemBatch

ALLOWED_MIME_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.docx'}

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


def validate_uploaded_file(file):
    """
    Validate that an uploaded file is an allowed type (PDF, image, or DOCX)
    and does not exceed the maximum size.
    Raises serializers.ValidationError on failure.
    """
    import os
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise serializers.ValidationError(
            f"Unsupported file type '{ext}'. Allowed: PDF, JPEG, PNG, GIF, WEBP, DOCX."
        )
    content_type = getattr(file, 'content_type', None)
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise serializers.ValidationError(
            f"Unsupported content type '{content_type}'."
        )
    if file.size > MAX_FILE_SIZE_BYTES:
        raise serializers.ValidationError(
            f"File '{file.name}' exceeds the 20 MB size limit."
        )


class InspectionDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectionDocument
        fields = ('id', 'file', 'label', 'uploaded_at')

    def validate_file(self, value):
        validate_uploaded_file(value)
        return value

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

class InspectionRelatedStockEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = StockEntry
        fields = ('id', 'entry_number', 'entry_type', 'status', 'entry_date')

class InspectionCertificateSerializer(serializers.ModelSerializer):
    items = InspectionItemSerializer(many=True)
    documents = InspectionDocumentSerializer(many=True, read_only=True)
    stock_entries = InspectionRelatedStockEntrySerializer(many=True, read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True)
    department_hierarchy_level = serializers.IntegerField(source='department.hierarchy_level', read_only=True)
    initiated_by_name = serializers.CharField(source='initiated_by.username', read_only=True)
    stock_filled_by_name = serializers.CharField(source='stock_filled_by.username', read_only=True, allow_null=True)
    central_store_filled_by_name = serializers.CharField(source='central_store_filled_by.username', read_only=True, allow_null=True)
    finance_reviewed_by_name = serializers.CharField(source='finance_reviewed_by.username', read_only=True, allow_null=True)
    rejected_by_name = serializers.CharField(source='rejected_by.username', read_only=True, allow_null=True)
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
            'stage', 'status', 'items', 'documents', 'stock_entries', 'is_initiated',
            'initiated_by', 'initiated_by_name', 'initiated_at',
            'stock_filled_by', 'stock_filled_by_name', 'stock_filled_at',
            'central_store_filled_by', 'central_store_filled_by_name', 'central_store_filled_at',
            'finance_reviewed_at', 'finance_reviewed_by', 'finance_reviewed_by_name', 'finance_check_date',
            'rejected_by', 'rejected_by_name', 'rejected_at', 'rejection_reason', 'rejection_stage',
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
            if hasattr(data, 'lists'):
                # QueryDict.copy() deep-copies values and crashes on uploaded files.
                # Validation only needs form fields; files are handled from request.FILES.
                data = {
                    key: values if len(values) > 1 else values[0]
                    for key, values in data.lists()
                    if not key.startswith('documents[') and key != 'file'
                }
            else:
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
                    if file_key.startswith('documents[') or file_key == 'file':
                        file = request.FILES[file_key]
                        validate_uploaded_file(file)
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
                    if file_key.startswith('documents[') or file_key == 'file':
                        file = request.FILES[file_key]
                        validate_uploaded_file(file)
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
