from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import os

class InspectionPDFGenerator:
    def __init__(self, inspection):
        self.inspection = inspection
        # Logo path: backend/inventory/assets/ned_logo.png
        self.logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "ned_logo.png")
        self.width, self.height = letter
        self.styles = getSampleStyleSheet()
        self.BOTTOM_MARGIN = 0  # Consistent with generator.py
        
        # 1. Prepare 'data' dictionary exactly as generator.py expects
        self.data = {
            'contract_no': self.inspection.contract_no,
            'date': self.inspection.date.strftime('%d/%m/%Y') if self.inspection.date else "________________",
            'contractor_name': self.inspection.contractor_name,
            'contractor_address': self.inspection.contractor_address or "",
            'indenter': self.inspection.indenter,
            'indent_no': self.inspection.indent_no,
            'consignee': self.inspection.consignee_name or "________________",
            'department': self.inspection.department.name if self.inspection.department else "________________",
            'date_of_delivery': self.inspection.date_of_delivery.strftime('%d/%m/%Y') if self.inspection.date_of_delivery else "________________",
            'delivery_status': self.inspection.get_delivery_type_display(),

            # Consignee section
            'date_of_inspection': self.inspection.date_of_inspection.strftime('%d/%m/%Y') if self.inspection.date_of_inspection else "________________",
            'stock_register_no': "________________",
            'stock_page_nos': "________________",
            'stock_date_of_entry': "________________",

            # Central Store section
            'dead_stock_register_no': "________________",
            'dead_stock_page_nos': "________________",
            'dead_stock_date_of_entry': "________________",

            # Finance section
            'purchase_section_date': self.inspection.finance_check_date.strftime('%d/%m/%Y') if self.inspection.finance_check_date else "________________",
        }

        # Populate register info from items if available
        first_item = self.inspection.items.first()
        if first_item:
            if first_item.stock_register:
                self.data['stock_register_no'] = first_item.stock_register.register_number
            elif first_item.stock_register_no:
                self.data['stock_register_no'] = first_item.stock_register_no
            
            if first_item.stock_register_page_no: self.data['stock_page_nos'] = first_item.stock_register_page_no
            if first_item.stock_entry_date: self.data['stock_date_of_entry'] = first_item.stock_entry_date.strftime('%d/%m/%Y')
            
            if first_item.central_register:
                self.data['dead_stock_register_no'] = first_item.central_register.register_number
            elif first_item.central_register_no:
                self.data['dead_stock_register_no'] = first_item.central_register_no
            if first_item.central_register_page_no: self.data['dead_stock_page_nos'] = first_item.central_register_page_no
        
        if self.inspection.central_store_filled_at:
            self.data['dead_stock_date_of_entry'] = self.inspection.central_store_filled_at.strftime('%d/%m/%Y')

        # 2. Prepare 'item_data' exactly as generator.py expects
        items = self.inspection.items.all()
        self.item_data = {
            'descriptions': [item.item_description for item in items],
            'acct_unit': [item.item.acct_unit if item.item else "Unit" for item in items],
            't_quantity': [str(item.tendered_quantity) for item in items],
            'r_quantity': [str(item.rejected_quantity) for item in items],
            'a_quantity': [str(item.accepted_quantity) for item in items]
        }

        # 3. Prepare 'rejected_item_data' exactly as generator.py expects
        self.rejected_item_data = {
            'item_no': [],
            'reasons': []
        }
        for idx, item in enumerate(items):
            if item.rejected_quantity > 0:
                self.rejected_item_data['item_no'].append(idx + 1)
                self.rejected_item_data['reasons'].append(item.remarks or "No Reason Provided")

    def generate(self, buffer):
        """Main entry point for Django ViewSet"""
        c = canvas.Canvas(buffer, pagesize=letter)
        self.generate_form(c)
        c.save()

    def generate_form(self, c):
        self.page_header(c)
        self.drawLogo(c)
        self.drawIndenterSection(c)
        self.page_footer(c)
        last_y = self.draw_item_table(c)
        last_y = self.drawConsigneeSection(c, last_y)
        last_y = self.drawCentralStoreSection(c, last_y)
        self.drawFinanceSection(c, last_y)
    
    def check_space_and_new_page(self, c, current_y, required_space):
        """Check if there's enough space, create new page if needed"""
        if current_y - required_space < self.BOTTOM_MARGIN:
            c.showPage()
            self.page_header(c)
            return self.height - 50
        return current_y
    
    def page_header(self, c):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(self.width - 163, self.height - 17, "F/QSP 10/06/01")
        
    def page_footer(self, c):
        c.setFont("Helvetica-Bold", 12) 
        c.drawString(self.width - 117, self.height - 750, "P.T.O")
    
    def drawLogo(self, c):
        image_path = self.logo_path
        if os.path.exists(image_path):
            c.drawImage(image_path, x=45, y=self.height - 100, width=inch, height=inch,
                        preserveAspectRatio=True, mask='auto')
        
    def drawIndenterSection(self, c):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(self.width - 163, self.height - 31.5, "Issued On: ______________")
        c.drawString(self.width - 163, self.height - 45.5, "Issued To: _______________")

        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(self.width / 2, self.height - 68, "NED UNIVERSITY OF ENGINEERING & TECHNOLOGY, KARACHI")
        c.drawCentredString(self.width / 2, self.height - 88, "PURCHASE SECTION")

        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(self.width / 2, self.height - 109, "INSPECTION CERTIFICATE")

        text_width = c.stringWidth("INSPECTION CERTIFICATE", "Helvetica-Bold", 14)
        c.setLineWidth(1)
        c.line((self.width - text_width) / 2, self.height - 111, (self.width + text_width) / 2, self.height - 111)

        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(self.width / 2, self.height - 133, "(To be completed by Consignee / Indenter) ")

        c.setFont("Helvetica", 11)
        c.drawCentredString(self.width / 2, self.height - 152,
                            "1. Contract No: _______________________________________________ Date:________________")
        c.drawString(self.width - 476, self.height - 152, f"{self.data['contract_no']}")
        c.drawString(self.width - 150, self.height - 152, f"{self.data['date']}")
        
        c.drawCentredString(self.width / 2, self.height - 170,
                            "2. Contractor's Name and address: ____________________________________________________")
        c.drawString(self.width - 370, self.height - 170, f"{self.data['contractor_name'] + ', ' + self.data['contractor_address']}")
        
        c.drawCentredString(self.width / 2, self.height - 188,
                            "3. Indenter. ________________________________ 4. Indent No ____________________________")
        c.drawString(self.width - 480, self.height - 188, f"{self.data['indenter']}")
        c.drawString(self.width - 220, self.height - 188, f"{self.data['indent_no']}")
        
        c.drawCentredString(self.width / 2, self.height - 206,
                            "5. Consignee: ________________________________ 6. Department: ________________________")
        c.drawString(self.width - 480, self.height - 206, f"{self.data['consignee']}")
        c.drawString(self.width - 200, self.height - 206, f"{self.data['department']}")
        
        c.drawCentredString(self.width / 2, self.height - 224,
                            "7. Date of Delivery. ____________________________ 8. Delivery in part or full _________________")
        c.drawString(self.width - 450, self.height - 224, f"{self.data['date_of_delivery']}")
        c.drawString(self.width - 160, self.height - 224, f"{self.data['delivery_status']}")

        c.drawString(self.width - 553, self.height - 242, "9. Details of Stores delivered.")
    
    def draw_item_table(self, c):
        normal = self.styles["Normal"]

        all_data = [
            ["Item No.", "DESCRIPTION OF STORES", "Acct. Unit",
            "Tendered\n(Quantity)", "Rejected\n(Quantity)", "Accepted\n(Quantity)"]
        ]

        for i in range(len(self.item_data['descriptions'])):
            all_data.append([
                str(i+1),
                Paragraph(self.item_data['descriptions'][i], normal),
                self.item_data['acct_unit'][i],
                self.item_data['t_quantity'][i],
                self.item_data['r_quantity'][i],
                self.item_data['a_quantity'][i]
            ])

        table_style = TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 1), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.white),
        ])

        x_margin = 40
        y_start = self.height - 260
        bottom_margin = self.height - 742

        header = all_data[0]
        rows = all_data[1:]
        current_y = y_start
        chunk = [header]

        for row in rows:
            temp = Table(chunk + [row],
                        colWidths=[0.7*inch, 3*inch, 0.8*inch, 1*inch, 1*inch, 1*inch])
            temp.setStyle(table_style)
            _, h = temp.wrap(self.width, self.height)
            
            if current_y - h < bottom_margin:  
                temp = Table(chunk, colWidths=[0.7*inch, 3*inch, 0.8*inch, 1*inch, 1*inch, 1*inch])
                temp.setStyle(table_style)
                _, h_chunk = temp.wrap(self.width, self.height)
                temp.drawOn(c, x_margin, current_y - h_chunk)

                c.showPage()
                self.page_footer(c)
                current_y = self.height - 50
                self.page_header(c)
                chunk = [header, row]
            else:
                chunk.append(row)

        if chunk:
            temp = Table(chunk, colWidths=[0.7*inch, 3*inch, 0.8*inch, 1*inch, 1*inch, 1*inch])
            temp.setStyle(table_style)
            _, h_chunk = temp.wrap(self.width, self.height)
            temp.drawOn(c, x_margin, current_y - h_chunk)

        c.showPage()
        self.page_header(c)
        return self.height

    def drawConsigneeSection(self, c, last_y):
        # Check space for header (74 pixels needed)
        last_y = self.check_space_and_new_page(c, last_y, 74)
        
        c.setFont("Helvetica-Bold", 12)
        c.drawString(self.width - 582, last_y - 74, "10. Consignee / Indentor:")
        
        # Check space for date line
        last_y = self.check_space_and_new_page(c, last_y - 74, 15)
        c.setFont("Helvetica", 12)
        c.drawString(self.width - 557, last_y - 15, "a) Date of Inspection _______________")
        c.drawString(self.width - 440, last_y - 15, f"{self.data['date_of_inspection']}")
        
        # Check space for certification text (about 54 pixels)
        last_y = self.check_space_and_new_page(c, last_y - 15, 54)
        c.setFont("Helvetica", 11)
        c.drawString(self.width - 557, last_y - 13, "b) Certified that the stores as mentioned on page 1 (para 9) have been received in good condition and")
        c.drawString(self.width - 542, last_y - 26, "according to specifications as given in the Contract Order; except the following for the reasons as")
        c.drawString(self.width - 542, last_y - 39, "below:")
        
        # Draw rejection table and get new position
        last_y = self.draw_rejection_table(c, last_y - 78)
        
        # Check space for stock register info (about 54 pixels needed)
        last_y = self.check_space_and_new_page(c, last_y, 54)
        
        c.setFont("Helvetica", 11)
        c.drawString(self.width - 567, last_y, "c) The stores received have been entered in Stock Register No. _____________________________________")
        c.drawString(self.width - 250, last_y, f"{self.data['stock_register_no']}")
        
        c.drawString(self.width - 553, last_y - 18, "Page No(s). ___________")
        c.drawString(self.width - 485, last_y - 18, f"{self.data['stock_page_nos']}")
        
        c.drawString(self.width - 567, last_y - 36, "d) Date of Entry: ___________________________")
        c.drawString(self.width - 485, last_y - 36, f"{self.data['stock_date_of_entry']}")
        
        # Check space for signature blocks (about 200 pixels)
        last_y = self.check_space_and_new_page(c, last_y - 36, 200)
        
        c.drawString(self.width - 242, last_y - 36, "Consignee's Signature _____________")
        c.drawString(self.width - 242, last_y - 54, "Name ___________________________")
        c.drawString(self.width - 242, last_y - 72, "Designation ___________________")
        
        c.drawString(self.width - 582, last_y - 102, "___________________ ")
        c.drawString(self.width - 582, last_y - 120, "Countersignature by")
        c.drawString(self.width - 582, last_y - 134, "Chairman / Head of the Department")
        c.drawString(self.width - 582, last_y - 148, "(if other than Consignee) ")
        
        c.setLineWidth(3)
        c.line(self.width - 582, last_y - 164, self.width - 30, last_y - 164)
        
        return last_y - 164
        
    def drawCentralStoreSection(self, c, last_y):
        # Check space for entire section (about 180 pixels)
        last_y = self.check_space_and_new_page(c, last_y, 180)
        
        c.setFont("Helvetica-Bold", 11)
        c.drawString(self.width - 582, last_y - 14, "11. Central Store:")
        
        c.setFont("Helvetica", 11)
        c.drawString(self.width - 559, last_y - 34, "a) The items have been registered in the Central Dead Stock Register (Non Stock) No:____________")
        c.drawString(self.width - 120, last_y - 34, f"{self.data['dead_stock_register_no']}")
        
        c.drawString(self.width - 548, last_y - 54, "Page No(s). ______________________________________________________________________")
        c.drawString(self.width - 480, last_y - 54, f"{self.data['dead_stock_page_nos']}")
        
        c.drawString(self.width - 559, last_y - 74, "b) Date of Entry:_________________")
        c.drawString(self.width - 460, last_y - 74, f"{self.data['dead_stock_date_of_entry']}")
        
        c.setFont("Helvetica-Bold", 11)
        c.drawString(self.width - 189, last_y - 120, "____________________")
        c.drawString(self.width - 189, last_y - 134, "Manager Central Store")

        c.setLineWidth(3)
        c.line(self.width - 582, last_y - 150, self.width - 30, last_y - 150)
        
        return last_y - 150
    
    def drawFinanceSection(self, c, last_y):
        # Check space for entire section (about 110 pixels)
        last_y = self.check_space_and_new_page(c, last_y, 110)
        
        c.setFont("Helvetica-Bold", 12)
        c.drawString(self.width - 582, last_y - 20, "12. Purchase Section, Directorate of Finance:")
        
        c.setFont("Helvetica", 12)
        c.drawString(self.width - 559, last_y - 36, "Checked and found all formalities of inspection have been completed.")
        
        c.setFont("Helvetica", 12)
        c.drawString(self.width - 582, last_y - 97, "Dated: ______________")
        c.drawString(self.width - 532, last_y - 97, f"{self.data['purchase_section_date']}")
        
        c.setFont("Helvetica-Bold", 12)
        c.drawString(self.width - 200, last_y - 97, "Assistant Director Finance")
        c.drawString(self.width - 160, last_y - 110, "(Purchase)")
       
    def draw_rejection_table(self, c, last_y, max_width=500):
        """Draws the rejection table with proper pagination"""
        normal = self.styles["Normal"]

        all_data = [["ITEM No", "REASONS FOR REJECTION"]]
        for i in range(len(self.rejected_item_data['item_no'])):
            all_data.append([
                str(self.rejected_item_data['item_no'][i]), 
                Paragraph(self.rejected_item_data['reasons'][i], normal)
            ])

        table_style = TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.white),
        ])
        header = all_data[0]
        rows = all_data[1:]
        current_y = last_y
        chunk = [header]

        for row in rows:
            temp = Table(chunk + [row], colWidths=[1*inch, max_width - 45])
            temp.setStyle(table_style)
            _, h = temp.wrap(max_width, self.height)
            
            if current_y - h < self.BOTTOM_MARGIN:
                temp = Table(chunk, colWidths=[1*inch, max_width - 45])
                temp.setStyle(table_style)
                _, h_chunk = temp.wrap(max_width, self.height)
                temp.drawOn(c, 40, current_y - h_chunk)

                c.showPage()
                self.page_header(c)
                current_y = self.height - 50
                chunk = [header, row]
            else:
                chunk.append(row)

        if chunk:
            temp = Table(chunk, colWidths=[1*inch, max_width - 45])
            temp.setStyle(table_style)
            _, h_chunk = temp.wrap(max_width, self.height)
            temp.drawOn(c, 40, current_y - h_chunk)
            current_y = current_y - h_chunk

        # Add overall rejection reason if it exists
        if self.inspection.rejection_reason:
            current_y = self.check_space_and_new_page(c, current_y, 40)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(40, current_y - 15, "OVERALL REJECTION REASON:")
            c.setFont("Helvetica-Oblique", 10)
            c.drawString(40, current_y - 28, f"{self.inspection.rejection_reason}")
            current_y -= 40

        return current_y - 20
