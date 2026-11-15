import markdown
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import re

# Read markdown file
with open('C:/Users/Zamuxolo/RAATS_Test/RAATS_Design_and_Implementation_Challenges_Report_Aug-Nov_2026_v0.3.md', 'r', encoding='utf-8') as f:
    md_content = f.read()

# Create document
doc = Document()

# Set default font
style = doc.styles['Normal']
font = style.font
font.name = 'Calibri'
font.size = 11

# Configure heading styles
for level in range(1, 4):
    heading_style = doc.styles[f'Heading {level}']
    heading_style.font.name = 'Calibri'
    heading_style.font.color.rgb = RGBColor(0, 51, 102)
    if level == 1:
        heading_style.font.size = 18
        heading_style.font.bold = True
    elif level == 2:
        heading_style.font.size = 14
        heading_style.font.bold = True
    elif level == 3:
        heading_style.font.size = 12
        heading_style.font.bold = True

def add_formatted_paragraph(doc, text):
    p = doc.add_paragraph()
    parts = re.split(r'(\*\*.*?\*\*|\*.*?\*|`.*?`)', text)
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            run = p.add_run(part[2:-2])
            run.bold = True
        elif part.startswith('*') and part.endswith('*') and not part.startswith('**'):
            run = p.add_run(part[1:-1])
            run.italic = True
        elif part.startswith('`') and part.endswith('`'):
            run = p.add_run(part[1:-1])
            run.font.name = 'Consolas'
            run.font.size = 9
            run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        else:
            run = p.add_run(part)
    p.paragraph_format.space_after = 6
    return p

# Parse markdown
lines = md_content.split('\n')
i = 0
in_code_block = False
code_lines = []
in_table = False
table_rows = []

while i < len(lines):
    line = lines[i]
    
    if line.strip() == '---' or line.strip() == '___':
        i += 1
        continue
    
    if line.strip().startswith('```'):
        if not in_code_block:
            in_code_block = True
            code_lines = []
        else:
            in_code_block = False
            if code_lines:
                p = doc.add_paragraph()
                run = p.add_run('\n'.join(code_lines))
                run.font.name = 'Consolas'
                run.font.size = 9
                run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
                from docx.oxml import OxmlElement
                from docx.oxml.ns import qn
                shading = OxmlElement('w:shd')
                shading.set(qn('w:fill'), 'F0F0F0')
                shading.set(qn('w:val'), 'clear')
                p.paragraph_format.element.get_or_add_pPr().append(shading)
                p.paragraph_format.space_before = 6
                p.paragraph_format.space_after = 6
        i += 1
        continue
    
    if in_code_block:
        code_lines.append(line)
        i += 1
        continue
    
    if '|' in line and line.strip().startswith('|') and line.strip().endswith('|'):
        if not in_table:
            in_table = True
            table_rows = []
        cells = [cell.strip() for cell in line.split('|')[1:-1]]
        table_rows.append(cells)
        i += 1
        continue
    elif in_table:
        if len(table_rows) > 1 and all(re.match(r'^[\s\-:]+$', cell) for cell in table_rows[1]):
            headers = table_rows[0]
            data_rows = table_rows[2:]
        else:
            headers = table_rows[0]
            data_rows = table_rows[1:]
        
        if headers:
            table = doc.add_table(rows=1 + len(data_rows), cols=len(headers))
            table.style = 'Table Grid'
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            
            for j, header in enumerate(headers):
                cell = table.rows[0].cells[j]
                cell.text = header
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
                        run.font.size = 9
            
            for row_idx, row in enumerate(data_rows):
                for j, cell_text in enumerate(row):
                    if j < len(table.columns):
                        cell = table.rows[row_idx + 1].cells[j]
                        cell.text = cell_text
                        for paragraph in cell.paragraphs:
                            for run in paragraph.runs:
                                run.font.size = 9
        
        in_table = False
        table_rows = []
        i += 1
        continue
    
    heading_match = re.match(r'^(#{1,6})\s+(.+)', line)
    if heading_match:
        level = min(len(heading_match.group(1)), 3)
        text = heading_match.group(2)
        doc.add_heading(text, level=level)
        i += 1
        continue
    
    if line.strip():
        p = doc.add_paragraph()
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*|`.*?`)', line)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                run = p.add_run(part[2:-2])
                run.bold = True
            elif part.startswith('*') and part.endswith('*') and not part.startswith('**'):
                run = p.add_run(part[1:-1])
                run.italic = True
            elif part.startswith('`') and part.endswith('`'):
                run = p.add_run(part[1:-1])
                run.font.name = 'Consolas'
                run.font.size = 9
                run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
            else:
                run = p.add_run(part)
        p.paragraph_format.space_after = 6
    
    i += 1

if in_code_block and code_lines:
    p = doc.add_paragraph()
    run = p.add_run('\n'.join(code_lines))
    run.font.name = 'Consolas'
    run.font.size = 9
    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

if in_table and table_rows:
    pass

output_path = 'C:/Users/Zamuxolo/RAATS_Test/RAATS_Design_and_Implementation_Challenges_Report_Aug-Nov_2026_v0.3.docx'
doc.save(output_path)
print(f'Saved to {output_path}')