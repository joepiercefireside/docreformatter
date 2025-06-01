import requests
import json
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging

logger = logging.getLogger(__name__)

def convert_content(content, template_prompt, conversion_prompt=None):
    headers = {
        "Authorization": f"Bearer {os.environ.get('API_KEY')}",
        "Content-Type": "application/json"
    }
    
    # Prepare components to avoid nested f-string expressions
    conversion_prompt_text = conversion_prompt if conversion_prompt else 'No additional conversion instructions.'
    source_content_json = json.dumps(content, indent=2)
    
    # Construct prompt for semantic structuring
    prompt = (
        "You are an AI tasked with reformatting source resume content into a structured JSON object based on a template prompt and an optional conversion prompt. "
        "Focus on semantic understanding and structuring the content into sections as defined by the template prompt, without applying any styling (e.g., fonts, colors). "
        "Use the conversion prompt to adjust tone, brevity, or other content instructions if provided.\n\n"
        "**Template Prompt**: " + template_prompt + "\n\n"
        "**Conversion Prompt**: " + conversion_prompt_text + "\n\n"
        "**Source Content**: " + source_content_json + "\n\n"
        "**Task**:\n"
        "1. Semantically analyze the source content, mapping sections to the template's structure (e.g., 'Career Experience' to 'Professional Experience').\n"
        "2. Apply the template prompt's instructions for section layout and semantics (e.g., what each section should contain).\n"
        "3. Apply the conversion prompt's instructions (e.g., tone, brevity) if provided.\n"
        "4. Deduplicate repeated content (e.g., contact info).\n"
        "5. Output a JSON object with template sections, content, and a section_order array.\n"
        "6. Do NOT include styling details (e.g., fonts, colors); styling will be applied later.\n\n"
        "**Output Format**:\n"
        "```json\n"
        "{\n"
        "  \"sections\": {\n"
        "    \"name\": \"String\",\n"
        "    \"contact\": \"String\",\n"
        "    \"professional summary\": \"String\",\n"
        "    \"core competencies\": [\"String\", ...],\n"
        "    \"professional experience\": [\n"
        "      {\n"
        "        \"company\": \"String\",\n"
        "        \"location\": \"String\",\n"
        "        \"dates\": \"String\",\n"
        "        \"role\": \"String\",\n"
        "        \"responsibilities\": \"String\",\n"
        "        \"achievements\": [\"String\", ...]\n"
        "      },\n"
        "      ...\n"
        "    ],\n"
        "    \"education\": [\"String\", ...],\n"
        "    \"professional affiliations\": [\"String\", ...]\n"
        "  },\n"
        "  \"section_order\": [\"name\", \"contact\", ...],\n"
        "  \"references\": [\"String\", ...]\n"
        "}\n"
        "```\n"
    )
    
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Convert the source content into the specified structure."}
        ],
        "max_tokens": 4096,
        "temperature": 0.7,
        "response_format": {"type": "json_object"}
    }
    
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    
    try:
        response = session.post(os.environ.get('AI_API_URL', 'https://api.openai.com/v1/chat/completions'), headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "choices" not in data or not data["choices"]:
            raise ValueError("No response from AI")
        converted = json.loads(data["choices"][0]["message"]["content"])
        logger.info(f"Converted content: {json.dumps(converted, indent=2)[:1000]}...")
        return converted
    except Exception as e:
        logger.error(f"Error converting content: {str(e)}")
        raise