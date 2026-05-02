from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


class InventoryPositionPDFGenerator:
    def __init__(self, report_data):
        self.report_data = report_data
        self.styles = getSampleStyleSheet()
        self.styles.add(
            ParagraphStyle(
                name='SectionHeading',
                parent=self.styles['Heading2'],
                fontName='Helvetica-Bold',
                fontSize=12,
                leading=14,
                spaceAfter=8,
                textColor=colors.HexColor('#1f2937'),
            )
        )
        self.styles.add(
            ParagraphStyle(
                name='SmallMuted',
                parent=self.styles['BodyText'],
                fontSize=8,
                leading=10,
                textColor=colors.HexColor('#4b5563'),
            )
        )

    def _apply_table_style(self, table, header_background=colors.HexColor('#334155')):
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), header_background),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]
        for row_index in range(1, len(table._cellvalues)):
            if row_index % 2 == 0:
                style.append(('BACKGROUND', (0, row_index), (-1, row_index), colors.HexColor('#f8fafc')))
        table.setStyle(TableStyle(style))
        return table

    def _build_totals_table(self):
        totals = self.report_data.get('totals') or {}
        data = [
            ['Available', 'Allocated', 'In Transit'],
            [
                str(totals.get('available_quantity', 0)),
                str(totals.get('allocated_quantity', 0)),
                str(totals.get('in_transit_quantity', 0)),
            ],
        ]
        table = Table(data, colWidths=[1.7 * inch, 1.7 * inch, 1.7 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dbe4f0')),
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#eef2f7')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#111827')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, 1), 12),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#94a3b8')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        return table

    def _build_summary_table(self):
        summary_rows = self.report_data.get('summary_rows') or []
        data = [[
            'Item Code',
            'Item Name',
            'Tracking Type',
            'Total',
            'Available',
            'Allocated',
            'In Transit',
        ]]

        if not summary_rows:
            data.append(['-', 'No summary rows available', '-', '0', '0', '0', '0'])
        else:
            for row in summary_rows:
                data.append([
                    str(row.get('item_code') or '-'),
                    Paragraph(str(row.get('item_name') or '-'), self.styles['BodyText']),
                    str(row.get('tracking_type') or '-'),
                    str(row.get('total') or 0),
                    str(row.get('available') or 0),
                    str(row.get('allocated') or 0),
                    str(row.get('in_transit') or 0),
                ])

        table = Table(
            data,
            colWidths=[0.85 * inch, 2.05 * inch, 1.0 * inch, 0.55 * inch, 0.7 * inch, 0.75 * inch, 0.7 * inch],
            repeatRows=1,
        )
        return self._apply_table_style(table)

    def _build_detail_table(self, rows, empty_message):
        data = [[
            'Item Name',
            'Status',
            'Holder',
            'Instance',
            'Batch',
            'Qty',
            'Stock Entry',
        ]]

        if not rows:
            data.append([empty_message, '-', '-', '-', '-', '-', '-'])
        else:
            for row in rows:
                holder_bits = [row.get('holder_type') or '', row.get('holder_name') or '']
                holder = ' - '.join(bit for bit in holder_bits if bit)
                data.append([
                    Paragraph(str(row.get('item_name') or '-'), self.styles['BodyText']),
                    str(row.get('status') or '-'),
                    Paragraph(holder or '-', self.styles['BodyText']),
                    str(row.get('instance_id') or '-'),
                    str(row.get('batch_number') or '-'),
                    str(row.get('quantity') or '-'),
                    str(row.get('stock_entry_number') or '-'),
                ])

        table = Table(
            data,
            colWidths=[1.65 * inch, 0.85 * inch, 1.5 * inch, 0.7 * inch, 0.95 * inch, 0.45 * inch, 1.0 * inch],
            repeatRows=1,
        )
        return self._apply_table_style(table)

    def generate(self, buffer):
        store = self.report_data.get('store') or {}
        generated_at = self.report_data.get('generated_at')
        generated_by = self.report_data.get('generated_by')
        store_name = store.get('name') or '-'
        store_code = store.get('code') or '-'

        doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        story = [
            Paragraph('Inventory Position Report', self.styles['Title']),
            Spacer(1, 6),
            Paragraph(f'Store: {store_name}', self.styles['Normal']),
            Paragraph(f'Store Code: {store_code}', self.styles['Normal']),
        ]

        if generated_at:
            story.append(Paragraph(f'Generated At: {generated_at}', self.styles['SmallMuted']))
        if generated_by:
            story.append(Paragraph(f'Generated By: {generated_by}', self.styles['SmallMuted']))

        story.extend([
            Spacer(1, 12),
            self._build_totals_table(),
            Spacer(1, 14),
            Paragraph('Inventory Summary', self.styles['SectionHeading']),
            self._build_summary_table(),
            Spacer(1, 16),
            Paragraph('Individual Instance Distribution', self.styles['SectionHeading']),
            self._build_detail_table(
                self.report_data.get('instance_rows') or [],
                'No individual instance rows available',
            ),
            Spacer(1, 16),
            Paragraph('Batch Distribution', self.styles['SectionHeading']),
            self._build_detail_table(
                self.report_data.get('batch_rows') or [],
                'No batch rows available',
            ),
        ])
        doc.build(story)
