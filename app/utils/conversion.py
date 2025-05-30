import requests
import json
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging

logger = logging.getLogger(__name__)

def convert_content(content, template_prompt, conversion_prompt):
    headers = {
        "Authorization": f"Bearer {os.environ.get('API_KEY')}",
        "Content-Type": "application/json"
    }
    prompt = f"""
You are an AI tasked with reformatting source resume content into a structured JSON object based on a template prompt and optional conversion prompt.

**Template Prompt**: {template_prompt}
**Conversion Prompt**: {conversion_prompt if conversion_prompt else 'No additional conversion instructions.'}
**Source Content**: {json.dumps(content, indent=2)}

**Task**:
1. Semantically analyze the source content, mapping sections to the template's structure (e.g., 'Career Experience' to 'Professional Experience').
2. Apply the template prompt's instructions for section layout and semantics.
3. Apply the conversion prompt's instructions (e.g., tone, brevity).
4. Deduplicate repeated content (e.g., contact info).
5. Output a JSON object with template sections, content, and a section_order array.
6. Exclude styling details (handled by the application).

**Output Format**:
```json
{
  "sections": {
    "name": "String",
    "contact": "String",
    "professional summary": "String",
    "core competencies": ["String", ...],
    "professional experience": [
      {
        "company": "String",
        "location": "String",
        "dates": "String",
        "role": "String",
        "responsibilities": "String",
        "achievements": ["String", ...]
      },
      ...
    ],
    "education": ["String", ...],
    "professional affiliations": ["String", ...]
  },
  "section_order": ["name", "contact", ...],
  "references": ["String", ...]
}
```
"""
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Convert the source content."}
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