from docx import Document
from werkzeug.utils import secure_filename
import os
import logging

logger = logging.getLogger(__name__)

def process_text_input(text):
    try:
        paragraphs = text.split('\n')
        content = {"text": [], "tables": [], "references": [], "section_order": []}
        current_section = None
        known_headers = ["introduction", "summary", "experience", "education", "affiliations", "skills", "competencies", "results", "conclusion", "profile", "contact", "name", "career experience"]

        for para in paragraphs:
            text = para.strip()
            if text:
                if text.lower().startswith("references"):
                    current_section = "References"
                    content["section_order"].append(current_section)
                    continue
                if current_section == "References":
                    content["references"].append(text)
                else:
                    is_header = (
                        text.isupper() or
                        len(text.split()) < 5 or
                        any(text.lower().startswith(h) for h in known_headers)
                    )
                    if is_header:
                        current_section = text
                        content["section_order"].append(current_section)
                    content["text"].append(f"[{current_section}] {text}" if current_section else text)
        
        logger.info(f"Processed text input section order: {content['section_order']}")
        return content
    except Exception as e:
        logger.error(f"Error processing text input: {str(e)}")
        raise

def process_docx(file):
    try:
        filename = secure_filename(file.filename)
        input_path = os.path.join('/tmp', filename)
        file.save(input_path)
        doc = Document(input_path)
        content = {"text": [], "tables": [], "references": [], "section_order": []}
        in_references = False
        current_section = None
        known_headers = ["introduction", "summary", "experience", "education", "affiliations", "skills", "competencies", "results", "conclusion", "profile", "contact", "name", "career experience"]

        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                if text.lower().startswith("references"):
                    in_references = True
                    current_section = "References"
                    content["section_order"].append(current_section)
                    continue
                if in_references:
                    content["references"].append(text)
                else:
                    is_header = (
                        para.runs and (
                            para.runs[0].bold or 
                            (para.runs[0].font.size is not None and para.runs[0].font.size.pt > 12)
                        ) or
                        text.isupper() or
                        any(text.lower().startswith(h) for h in known_headers)
                    )
                    if is_header:
                        current_section = text
                        content["section_order"].append(current_section)
                    content["text"].append(f"[{current_section}] {text}" if current_section else text)

        for table in doc.tables:
            table_data = []
            for row in table.rows:
                row_data = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_data:
                    table_data.append(row_data)
            if table_data:
                logger.info(f"Extracted table: {table_data}")
                content["tables"].append(table_data)
        os.remove(input_path)
        logger.info(f"Source section order: {content['section_order']}")
        return content
    except Exception as e:
        logger.error(f"Error processing docx: {str(e)}")
        raise