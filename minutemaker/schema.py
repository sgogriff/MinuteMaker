"""JSON schema definition and validation for LLM output."""

import json
import logging
import re

logger = logging.getLogger("minutemaker")

# The JSON schema that the LLM must return.
# This is used both for validation and as documentation in the system prompt.
MINUTES_SCHEMA = {
    "type": "object",
    "required": ["meeting_date", "chair", "secretary", "sections"],
    "properties": {
        "meeting_date": {
            "type": "string",
            "description": "Meeting date in the template's date format (e.g. DD/MM/YYYY)",
        },
        "chair": {
            "type": "string",
            "description": "Name of the chair, or 'Check Meeting Schedule' if not stated",
        },
        "secretary": {
            "type": "string",
            "description": "Name of the secretary, or 'Check Meeting Schedule' if not stated",
        },
        "sections": {
            "type": "array",
            "description": "All mandatory sections, in template order",
            "items": {
                "type": "object",
                "required": ["name", "items"],
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Section name exactly as defined in the template",
                    },
                    "items": {
                        "type": "array",
                        "description": "List of bullet points for this section",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "optional_sections": {
            "type": "array",
            "description": "Optional sections — only include if the notes contain relevant content",
            "items": {
                "type": "object",
                "required": ["name", "items"],
                "properties": {
                    "name": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


def schema_as_prompt() -> str:
    """Return a human-readable JSON schema description for embedding in the LLM prompt."""
    return json.dumps(MINUTES_SCHEMA, indent=2)


def extract_json(raw: str) -> str:
    """Extract a JSON object from LLM output that may contain markdown fences or commentary."""
    stripped = raw.strip()

    # Try direct parse first
    if stripped.startswith("{"):
        return stripped

    # Strip markdown code fences
    if "```" in stripped:
        # Find content between fences
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL)
        if match:
            return match.group(1).strip()

    # Last resort: find the outermost { ... }
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]

    return stripped


def parse_and_validate(raw_response: str) -> dict:
    """Parse LLM response as JSON and validate against the schema.

    Returns the parsed dict. Raises ValueError on parse or validation failure.
    """
    json_str = extract_json(raw_response)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    # Validate required top-level fields
    for field in ("meeting_date", "chair", "secretary", "sections"):
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    if not isinstance(data["sections"], list):
        raise ValueError("'sections' must be a list")

    # Validate each section
    for i, section in enumerate(data["sections"]):
        if not isinstance(section, dict):
            raise ValueError(f"Section {i} is not an object")
        if "name" not in section:
            raise ValueError(f"Section {i} missing 'name'")
        if "items" not in section:
            raise ValueError(f"Section {i} missing 'items'")
        if not isinstance(section["items"], list):
            raise ValueError(f"Section {i} 'items' must be a list")

    # Validate optional sections if present
    if "optional_sections" in data:
        if not isinstance(data["optional_sections"], list):
            raise ValueError("'optional_sections' must be a list")
        for i, section in enumerate(data["optional_sections"]):
            if not isinstance(section, dict):
                raise ValueError(f"Optional section {i} is not an object")
            if "name" not in section:
                raise ValueError(f"Optional section {i} missing 'name'")
            if "items" not in section:
                raise ValueError(f"Optional section {i} missing 'items'")

    # Check mandatory sections against template (done later with template config)
    logger.info("JSON validation passed")
    return data
