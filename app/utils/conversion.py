import requests
import json
import logging
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

def convert_content(content, template_prompt, conversion_prompt):
    """
    Convert raw content into a structured format using LLM based on the template prompt.
    
    Args:
        content (str): The raw content extracted from the source document.
        template_prompt (str): The prompt defining the structure and style.
        conversion_prompt (str): Additional instructions for tone, brevity, etc.
    
    Returns:
        dict: Structured content in JSON format.
    
    Raises:
        Exception: If the API call fails.
    """
    try:
        # Prepare the system prompt for the LLM
        system_prompt = (
            "You are an AI assistant tasked with converting raw content into a structured JSON format "
            "based on a template prompt, followed by applying additional conversion instructions.\n\n"
            "**Step 1: Structure the Content Using the Template Prompt**\n"
            "Use the following template prompt to define the structure, sections, and semantics of the output:\n\n"
            "**Template Prompt**:\n" + template_prompt + "\n\n"
            "Based on the template prompt, structure the raw content into sections such as headers, contact info, "
            "professional summary, core competencies, professional experience, education, etc. Ensure the content "
            "is organized according to the template's specified layout and semantics.\n\n"
            "**Step 2: Apply Conversion Instructions (if provided)**\n"
        )
        if conversion_prompt:
            system_prompt += (
                "After structuring the content, apply the following conversion instructions to modify the tone, brevity, "
                "or other attributes of the content as specified:\n\n"
                "**Conversion Instructions**:\n" + conversion_prompt + "\n\n"
                "For example, if the conversion instructions specify a more professional tone or concise wording, "
                "rewrite the structured content accordingly while preserving the structure defined by the template prompt.\n\n"
            )
            logger.info(f"Conversion prompt provided: {conversion_prompt}")
        else:
            system_prompt += "No additional conversion instructions provided. Proceed with the structured content as is.\n\n"
            logger.info("No conversion prompt provided.")

        system_prompt += (
            "**Output Format**:\n"
            "Return a JSON object with the following structure:\n"
            "```json\n"
            "{\n"
            "  \"sections\": {\n"
            "    \"name\": \"Full Name\",\n"
            "    \"contact\": \"Contact Info\",\n"
            "    \"professional_summary\": \"Summary text\",\n"
            "    \"core_competencies\": [\"Skill 1\", \"Skill 2\", ...],\n"
            "    \"professional_experience\": [\n"
            "      \"Company Name - Title, Location, Dates\",\n"
            "      \"- Responsibility 1\",\n"
            "      \"- Responsibility 2\"\n"
            "    ],\n"
            "    \"education\": [\"Degree, School, Location, Dates\"],\n"
            "    ...\n"
            "  }\n"
            "}\n"
            "```\n"
            "Ensure the content is structured according to the template prompt and then modified by the conversion instructions."
        )

        # Prepare the user prompt with the raw content
        user_prompt = "Here is the raw content to convert:\n\n" + content

        # Prepare the API payload
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 3000,
            "temperature": 0.7
        }

        # Set up the request with retries
        headers = {
            "Authorization": f"Bearer {os.environ.get('API_KEY')}",
            "Content-Type": "application/json"
        }
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))

        # Make the API call
        response = session.post(
            os.environ.get('AI_API_URL', 'https://api.openai.com/v1/chat/completions'),
            headers=headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()

        # Parse the response
        data = response.json()
        if "choices" not in data or not data["choices"]:
            raise ValueError("No response from AI")

        # Extract and parse the structured content
        converted_content = json.loads(data["choices"][0]["message"]["content"])
        logger.info(f"Converted content: {json.dumps(converted_content, indent=2)[:500]}...")
        return converted_content

    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            logger.error("API authentication failed: Invalid or missing API key.")
            raise Exception("Conversion failed: Invalid or missing API key. Please contact the administrator to verify the API configuration.")
        logger.error(f"Error converting content: {str(e)}")
        raise Exception(f"Conversion failed due to an API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error converting content: {str(e)}")
        raise Exception(f"Conversion failed: {str(e)}")