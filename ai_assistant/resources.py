"""Read-only assistant tools reuse the same permission/scoping API as the UI.

There is deliberately no SQL interpreter, database URI, arbitrary URL, or write
tool available to the model.
"""
from django.http import HttpRequest, QueryDict
from rest_framework.exceptions import APIException
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request


class AssistantPagination(PageNumberPagination):
    page_size = 25


def read_inventory_resource(user, resource: str, search: str = '', page: int = 1):
    from inventory import views

    resources = {
        'items': views.ItemViewSet,
        'distribution': views.StockRecordViewSet,
        'locations': views.LocationViewSet,
        'inspections': views.InspectionViewSet,
        'stock-entries': views.StockEntryViewSet,
        'maintenance': views.MaintenanceWorkOrderViewSet,
        'depreciation': views.FixedAssetRegisterEntryViewSet,
    }
    view_cls = resources.get(resource)
    if view_cls is None or not isinstance(page, int) or not 1 <= page <= 20:
        return {'error': 'Unsupported resource or page.'}
    raw = HttpRequest()
    raw.method = 'GET'
    raw.META.update(SERVER_NAME='localhost', SERVER_PORT='80')
    raw.GET = QueryDict('', mutable=True)
    raw.GET.update({'search': search[:200], 'page': str(page)})
    request = Request(raw, authenticators=[])
    request.user = user
    view = view_cls()
    view.request = request
    view.action = 'list'
    view.args, view.kwargs, view.format_kwarg = (), {}, None
    view.pagination_class = AssistantPagination
    try:
        view.check_permissions(request)
        return view.list(request).data
    except APIException as exc:
        return {'error': str(exc.detail), 'status': exc.status_code}
