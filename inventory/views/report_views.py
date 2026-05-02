from io import BytesIO

from django.http import Http404, HttpResponse
from rest_framework import status, viewsets
from rest_framework.response import Response

from ..models import Location
from ..permissions import ReportsPermission
from ..services.report_service import build_inventory_position_report
from ..utils.inventory_position_pdf import InventoryPositionPDFGenerator
from .utils import get_item_scope_locations


class ReportViewSet(viewsets.ViewSet):
    permission_classes = [ReportsPermission]

    def stores(self, request):
        stores = (
            get_item_scope_locations(request.user)
            .filter(is_store=True, is_active=True)
            .order_by('name', 'id')
        )
        return Response([
            {
                'id': store.id,
                'name': store.name,
                'code': store.code,
            }
            for store in stores
        ])

    def inventory_position_pdf(self, request):
        store_param = request.query_params.get('store')
        if store_param is None:
            return Response({'detail': 'store is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            store_id = int(store_param)
        except (TypeError, ValueError):
            return Response({'detail': 'store must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            store = Location.objects.get(id=store_id, is_active=True)
        except Location.DoesNotExist as exc:
            raise Http404 from exc

        if not store.is_store:
            return Response({'detail': 'store must reference a store location'}, status=status.HTTP_400_BAD_REQUEST)

        in_scope = get_item_scope_locations(request.user).filter(id=store.id).exists()
        if not in_scope:
            return Response({'detail': 'You do not have access to this store'}, status=status.HTTP_403_FORBIDDEN)

        report_data = build_inventory_position_report(store)
        report_data['generated_by'] = request.user.get_username()

        buffer = BytesIO()
        InventoryPositionPDFGenerator(report_data).generate(buffer)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="Inventory_Position_{store.code}.pdf"'
        return response
