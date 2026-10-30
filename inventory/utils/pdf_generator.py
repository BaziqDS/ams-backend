"""Connect the supplied certificate template to Django's existing PDF endpoint.

The original template is kept unchanged in generator.py. Its constructor writes
straight to a contract-derived filename, so this adapter initializes its state
and renders to the response's file-like buffer instead.
"""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas

from .generator import InspectionCertificateGenerator


def _date(value):
    return value.strftime('%d/%m/%Y') if value else ''


def _unique(values):
    return ', '.join(dict.fromkeys(str(value) for value in values if value))


def _paragraph(value):
    # ReportLab Paragraph interprets XML; stored descriptions are plain text.
    return escape(value or '').replace('\n', '<br/>')


class InspectionPDFGenerator(InspectionCertificateGenerator):
    def __init__(self, certificate):
        self.logo_path = str(Path(__file__).resolve().parent.parent / 'assets' / 'ned_logo.png')
        self.width, self.height = letter
        self.styles = getSampleStyleSheet()
        self.BOTTOM_MARGIN = 0  # Preserve the supplied template's layout.

        items = list(certificate.items.select_related('item', 'stock_register', 'central_register').order_by('id'))
        self.data = {
            'contract_no': certificate.contract_no,
            'date': _date(certificate.contract_date),
            'contractor_name': certificate.contractor_name or '',
            'contractor_address': certificate.contractor_address or '',
            'indenter': certificate.indenter or '',
            'indent_no': certificate.indent_no or '',
            'consignee': certificate.consignee_name or '',
            'department': certificate.department.name,
            'date_of_delivery': _date(certificate.date_of_delivery),
            'delivery_status': certificate.get_delivery_type_display(),
            'date_of_inspection': _date(certificate.date_of_inspection),
            'stock_register_no': _unique(
                row.stock_register.register_number if row.stock_register_id else row.stock_register_no
                for row in items
            ),
            'stock_page_nos': _unique(row.stock_register_page_no for row in items),
            'stock_date_of_entry': _unique(_date(row.stock_entry_date) for row in items),
            'dead_stock_register_no': _unique(
                row.central_register.register_number if row.central_register_id else row.central_register_no
                for row in items
            ),
            'dead_stock_page_nos': _unique(row.central_register_page_no for row in items),
            'dead_stock_date_of_entry': _date(certificate.central_store_filled_at),
            'purchase_section_date': _date(certificate.finance_check_date),
        }
        self.item_data = {
            'descriptions': [_paragraph(row.item_description) for row in items],
            'acct_unit': [row.item.acct_unit if row.item_id else '' for row in items],
            't_quantity': [row.tendered_quantity for row in items],
            'r_quantity': [row.rejected_quantity for row in items],
            'a_quantity': [row.accepted_quantity for row in items],
        }
        rejected = [(number, row) for number, row in enumerate(items, 1) if row.rejected_quantity > 0]
        self.rejected_item_data = {
            'item_no': [number for number, row in rejected],
            'reasons': [_paragraph(row.remarks) for number, row in rejected],
        }

    def generate(self, output):
        self.generate_form(canvas.Canvas(output, pagesize=letter))
