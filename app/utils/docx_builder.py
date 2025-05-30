from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import logging

logger = logging.getLogger(__name__)

def apply_docx_style(paragraph, style):
    for run in paragraph.runs:
        run.font.name = style.get("font", "Arial")
        run.font.size = Pt(style.get("size_pt", 11))
        run.bold = style.get("bold", False)
        run.font.color.rgb = RGBColor(*style.get("color_rgb", [0, 0, 0]))
    paragraph.paragraph_format.alignment = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY
    }.get(style.get("alignment", "left"), WD_ALIGN_PARAGRAPH.LEFT)
    paragraph.paragraph_format.space_before = Pt(style.get("spacing_before_pt", 6))
    paragraph.paragraph_format.space_after = Pt(style.get("spacing_after_pt", 6))

def create_reformatted_docx(sections, output_path, template_path=None):
    try:
        doc = Document()
        template_doc = Document(template_path) if template_path and os.path.exists(template_path) else None
        
        def extract_styles(doc):
            styles = {}
            current_section = None
            for para in doc.paragraphs:
                text = para.text.strip().lower()
                if not text or not para.runs:
                    continue
                run = para.runs[0]
                is_header = (
                    run.bold or
                    (run.font.size is not None and run.font.size.pt > 12) or
                    text in ["name", "contact", "professional summary", "core competencies", "professional experience", "education", "professional affiliations"]
                )
                if is_header:
                    current_section = para.text.strip()
                    styles[current_section.lower()] = {
                        "font": run.font.name or "Arial",
                        "size_pt": run.font.size.pt if run.font.size else 12,
                        "bold": run.bold if run.bold is not None else True,
                        "color_rgb": [run.font.color.rgb.red, run.font.color.rgb.green, run.font.color.rgb.blue] if run.font.color.rgb else [0, 0, 0],
                        "alignment": {WD_ALIGN_PARAGRAPH.LEFT: "left", WD_ALIGN_PARAGRAPH.CENTER: "center", WD_ALIGN_PARAGRAPH.RIGHT: "right", WD_ALIGN_PARAGRAPH.JUSTIFY: "justify"}.get(para.paragraph_format.alignment, "left"),
                        "spacing_before_pt": para.paragraph_format.space_before.pt if para.paragraph_format.space_before else 6,
                        "spacing_after_pt": para.paragraph_format.space_after.pt if para.paragraph_format.space_after else 6,
                        "is_horizontal_list": "•" in para.text and text.count('\n') <= 1
                    }
                elif current_section:
                    styles[f"{current_section.lower()}_item"] = {
                        "font": run.font.name or "Arial",
                        "size_pt": run.font.size.pt if run.font.size else 11,
                        "bold": run.bold if run.bold is not None else False,
                        "color_rgb": [run.font.color.rgb.red, run.font.color.rgb.green, run.font.color.rgb.blue] if run.font.color.rgb else [0, 0, 0],
                        "alignment": {WD_ALIGN_PARAGRAPH.LEFT: "left", WD_ALIGN_PARAGRAPH.CENTER: "center", WD_ALIGN_PARAGRAPH.RIGHT: "right", WD_ALIGN_PARAGRAPH.JUSTIFY: "justify"}.get(para.paragraph_format.alignment, "left"),
                        "spacing_before_pt": para.paragraph_format.space_before.pt if para.paragraph_format.space_before else 0,
                        "spacing_after_pt": para.paragraph_format.space_after.pt if para.paragraph_format.space_after else 0,
                        "is_horizontal_list": "•" in para.text and text.count('\n') <= 1
                    }
            return styles

        styles = extract_styles(template_doc) if template_doc else {
            "default": {
                "font": "Arial",
                "size_pt": 11,
                "bold": False,
                "color_rgb": [0, 0, 0],
                "alignment": "left",
                "spacing_before_pt": 6,
                "spacing_after_pt": 6,
                "is_horizontal_list": False
            }
        }

        for section_key in sections.get("section_order", []):
            if section_key not in sections["sections"]:
                continue
            value = sections["sections"][section_key]
            if not value or (isinstance(value, str) and not value.strip()) or (isinstance(value, list) and not value):
                continue

            display_key = section_key.replace('_', ' ').title()
            style = styles.get(section_key.lower(), styles.get("default"))

            para = doc.add_paragraph(display_key)
            apply_docx_style(para, style)

            if section_key == "core competencies" and style.get("is_horizontal_list", False):
                para = doc.add_paragraph(" • ".join(value))
                apply_docx_style(para, styles.get(f"{section_key.lower()}_item", style))
            elif section_key == "professional experience":
                for entry in value:
                    para = doc.add_paragraph(f"{entry['company']} – {entry['location']}")
                    apply_docx_style(para, styles.get(f"{section_key.lower()}_item", style))
                    para = doc.add_paragraph(f"{entry['role']} ({entry['dates']})")
                    apply_docx_style(para, styles.get(f"{section_key.lower()}_item", style))
                    para = doc.add_paragraph(entry['responsibilities'])
                    apply_docx_style(para, styles.get(f"{section_key.lower()}_item", style))
                    for achievement in entry.get('achievements', []):
                        para = doc.add_paragraph(achievement, style="List Bullet")
                        apply_docx_style(para, styles.get(f"{section_key.lower()}_item", style))
            elif isinstance(value, list):
                for item in value:
                    para = doc.add_paragraph(item, style="List Bullet")
                    apply_docx_style(para, styles.get(f"{section_key.lower()}_item", style))
            else:
                para = doc.add_paragraph(value)
                apply_docx_style(para, styles.get(f"{section_key.lower()}_item", style))

        doc.save(output_path)
        logger.info(f"Successfully created reformatted document: {output_path}")
    except Exception as e:
        logger.error(f"Error creating reformatted docx: {str(e)}")
        raise