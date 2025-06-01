from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from io import BytesIO
import os
from tempfile import NamedTemporaryFile

def create_reformatted_docx(structured_content, template_file):
    doc = Document()
    
    # If a template file is provided, extract styles from it
    template_styles = {}
    if template_file:
        with NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
            temp_file.write(template_file)
            temp_file_path = temp_file.name
        template_doc = Document(temp_file_path)
        os.unlink(temp_file_path)

        current_section = None
        for para in template_doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            is_header = (
                para.runs and (
                    para.runs[0].bold or
                    (para.runs[0].font.size is not None and para.runs[0].font.size > Pt(12))
                ) or
                text.isupper()
            )
            if is_header:
                current_section = text.lower()
                style = {
                    "font": para.runs[0].font.name or "Arial" if para.runs else "Arial",
                    "size_pt": para.runs[0].font.size.pt if para.runs and para.runs[0].font.size else 12,
                    "bold": para.runs[0].bold if para.runs and para.runs[0].bold is not None else False,
                    "color_rgb": [para.runs[0].font.color.rgb.red, para.runs[0].font.color.rgb.green, para.runs[0].font.color.rgb.blue] if para.runs and para.runs[0].font.color.rgb else [0, 0, 0],
                    "alignment": {WD_ALIGN_PARAGRAPH.LEFT: "left", WD_ALIGN_PARAGRAPH.CENTER: "center", WD_ALIGN_PARAGRAPH.RIGHT: "right", WD_ALIGN_PARAGRAPH.JUSTIFY: "justify"}.get(para.paragraph_format.alignment, "left"),
                    "spacing_before_pt": para.paragraph_format.space_before.pt if para.paragraph_format.space_before else 6,
                    "spacing_after_pt": para.paragraph_format.space_after.pt if para.paragraph_format.space_after else 6,
                    "is_horizontal_list": "•" in text and text.count('\n') <= 1
                }
                template_styles[current_section] = style

    # Apply structured content to the document with styles
    sections = structured_content.get("sections", {})
    section_order = structured_content.get("section_order", list(sections.keys()))

    for section_key in section_order:
        if section_key not in sections:
            continue
        style = template_styles.get(section_key.lower(), {
            "font": "Arial",
            "size_pt": 12,
            "bold": False,
            "color_rgb": [0, 0, 0],
            "alignment": "left",
            "spacing_before_pt": 6,
            "spacing_after_pt": 6,
            "is_horizontal_list": False
        })

        # Add section header
        para = doc.add_paragraph(section_key.replace('_', ' ').title())
        run = para.runs[0]
        run.font.name = style["font"]
        run.font.size = Pt(style["size_pt"])
        run.bold = style["bold"]
        run.font.color.rgb = RGBColor(*style["color_rgb"])
        para.paragraph_format.alignment = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY
        }.get(style["alignment"], WD_ALIGN_PARAGRAPH.LEFT)
        para.paragraph_format.space_before = Pt(style["spacing_before_pt"])
        para.paragraph_format.space_after = Pt(style["spacing_after_pt"])

        # Add section content
        content = sections[section_key]
        if isinstance(content, list):
            if style["is_horizontal_list"]:
                para = doc.add_paragraph(" • ".join(content))
                run = para.runs[0]
                run.font.name = style["font"]
                run.font.size = Pt(style["size_pt"] - 1)  # Slightly smaller for content
                run.bold = False
                run.font.color.rgb = RGBColor(*style["color_rgb"])
                para.paragraph_format.alignment = {
                    "left": WD_ALIGN_PARAGRAPH.LEFT,
                    "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "right": WD_ALIGN_PARAGRAPH.RIGHT,
                    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY
                }.get(style["alignment"], WD_ALIGN_PARAGRAPH.LEFT)
                para.paragraph_format.space_before = Pt(style["spacing_before_pt"])
                para.paragraph_format.space_after = Pt(style["spacing_after_pt"])
            else:
                for item in content:
                    if isinstance(item, dict):  # e.g., professional experience
                        for key, val in item.items():
                            para = doc.add_paragraph(f"{key.title()}: {val}")
                            run = para.runs[0]
                            run.font.name = style["font"]
                            run.font.size = Pt(style["size_pt"] - 1)
                            run.bold = False
                            run.font.color.rgb = RGBColor(*style["color_rgb"])
                            para.paragraph_format.alignment = {
                                "left": WD_ALIGN_PARAGRAPH.LEFT,
                                "center": WD_ALIGN_PARAGRAPH.CENTER,
                                "right": WD_ALIGN_PARAGRAPH.RIGHT,
                                "justify": WD_ALIGN_PARAGRAPH.JUSTIFY
                            }.get(style["alignment"], WD_ALIGN_PARAGRAPH.LEFT)
                            para.paragraph_format.space_before = Pt(style["spacing_before_pt"])
                            para.paragraph_format.space_after = Pt(style["spacing_after_pt"])
                    else:
                        para = doc.add_paragraph(item, style="List Bullet" if item.startswith("•") else None)
                        run = para.runs[0]
                        run.font.name = style["font"]
                        run.font.size = Pt(style["size_pt"] - 1)
                        run.bold = False
                        run.font.color.rgb = RGBColor(*style["color_rgb"])
                        para.paragraph_format.alignment = {
                            "left": WD_ALIGN_PARAGRAPH.LEFT,
                            "center": WD_ALIGN_PARAGRAPH.CENTER,
                            "right": WD_ALIGN_PARAGRAPH.RIGHT,
                            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY
                        }.get(style["alignment"], WD_ALIGN_PARAGRAPH.LEFT)
                        para.paragraph_format.space_before = Pt(style["spacing_before_pt"])
                        para.paragraph_format.space_after = Pt(style["spacing_after_pt"])
        else:
            para = doc.add_paragraph(content)
            run = para.runs[0]
            run.font.name = style["font"]
            run.font.size = Pt(style["size_pt"] - 1)
            run.bold = False
            run.font.color.rgb = RGBColor(*style["color_rgb"])
            para.paragraph_format.alignment = {
                "left": WD_ALIGN_PARAGRAPH.LEFT,
                "center": WD_ALIGN_PARAGRAPH.CENTER,
                "right": WD_ALIGN_PARAGRAPH.RIGHT,
                "justify": WD_ALIGN_PARAGRAPH.JUSTIFY
            }.get(style["alignment"], WD_ALIGN_PARAGRAPH.LEFT)
            para.paragraph_format.space_before = Pt(style["spacing_before_pt"])
            para.paragraph_format.space_after = Pt(style["spacing_after_pt"])

    # Add references if present
    references = structured_content.get("references", [])
    if references:
        para = doc.add_paragraph("References")
        run = para.runs[0]
        run.font.name = "Arial"
        run.font.size = Pt(12)
        run.bold = True
        run.font.color.rgb = RGBColor(0, 0, 0)
        para.paragraph_format.space_before = Pt(6)
        para.paragraph_format.space_after = Pt(6)

        for ref in references:
            para = doc.add_paragraph(ref, style="List Bullet")
            run = para.runs[0]
            run.font.name = "Arial"
            run.font.size = Pt(11)
            run.bold = False
            run.font.color.rgb = RGBColor(0, 0, 0)
            para.paragraph_format.space_before = Pt(6)
            para.paragraph_format.space_after = Pt(6)

    # Save the document to a BytesIO object for download
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer