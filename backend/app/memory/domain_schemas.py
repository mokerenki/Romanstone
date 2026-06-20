import json
from typing import Dict, Any

# =============================================================================
# PERSONAL ASSISTANCE SCHEMA (focus of the first vertical)
# =============================================================================
PERSONAL_ASSISTANCE_SCHEMA = {
    "entities": [
        {
            "label": "User",
            "properties": ["user_id", "name", "email", "phone"]
        },
        {
            "label": "Task",
            "properties": [
                "task_id", "title", "description",
                "status",          # todo | in_progress | done | urgent
                "priority",        # high | medium | low
                "due_date",
                "created_date",
                "completed_date"
            ]
        },
        {
            "label": "Event",
            "properties": [
                "event_id", "name", "date", "start_time", "end_time",
                "location", "description", "is_all_day"
            ]
        },
        {
            "label": "Contact",
            "properties": [
                "contact_id", "name", "relationship",      # e.g. "client", "opposing counsel"
                "email", "phone", "company", "notes",
                "last_contacted_date"
            ]
        },
        {
            "label": "Note",
            "properties": ["note_id", "title", "content", "created_date", "tags"]
        },
        {
            "label": "NewsArticle",
            "properties": [
                "news_id", "title", "source", "url",
                "date_published", "summary", "category",
                "relevance_score"          # 0‑1 how relevant to the user
            ]
        },
        {
            "label": "Briefing",
            "properties": [
                "briefing_id", "date", "time_generated",
                "content_summary",          # the full briefing text
                "sections"                  # list of section names included
            ]
        }
    ],
    "relationships": [
        # Task ownership and dependencies
        {"type": "ASSIGNED_TO",        "from": "Task",    "to": "User"},
        {"type": "RELATED_TO",         "from": "Task",    "to": "Event"},
        {"type": "DEPENDS_ON",         "from": "Task",    "to": "Task"},
        {"type": "BLOCKS",             "from": "Task",    "to": "Task"},

        # Contacts
        {"type": "HAS_CONTACT",        "from": "User",    "to": "Contact"},
        {"type": "CONTACT_FOR",        "from": "Contact", "to": "Task"},     # whom to call about a task

        # Events
        {"type": "ATTENDS",            "from": "User",    "to": "Event"},
        {"type": "ORGANISES",          "from": "User",    "to": "Event"},

        # Notes
        {"type": "REFERENCES",         "from": "Note",    "to": "Task"},
        {"type": "ABOUT",              "from": "Note",    "to": "Contact"},
        {"type": "RELATED_TO_EVENT",   "from": "Note",    "to": "Event"},

        # News
        {"type": "RELEVANT_TO_USER",   "from": "NewsArticle", "to": "User"},
        {"type": "TAGGED_WITH_TASK",   "from": "NewsArticle", "to": "Task"},
        {"type": "TAGGED_WITH_CONTACT","from": "NewsArticle", "to": "Contact"},

        # Briefing (historical record)
        {"type": "GENERATED_FOR",      "from": "Briefing","to": "User"},
        {"type": "INCLUDES_TASK",      "from": "Briefing","to": "Task"},
        {"type": "INCLUDES_EVENT",     "from": "Briefing","to": "Event"},
        {"type": "INCLUDES_CONTACT",   "from": "Briefing","to": "Contact"},
        {"type": "INCLUDES_NEWS",      "from": "Briefing","to": "NewsArticle"}
    ]
}

# =============================================================================
# LEGAL, PROCUREMENT, HEALTHCARE (unchanged, kept for later verticals)
# =============================================================================
LEGAL_SCHEMA = { ... }          # same as before
PROCUREMENT_SCHEMA = { ... }    # same as before
HEALTHCARE_SCHEMA = { ... }     # same as before

# =============================================================================
# Aggregation & Utilities
# =============================================================================
ALL_DOMAIN_SCHEMAS = {
    "personal_assistance": PERSONAL_ASSISTANCE_SCHEMA,
    "legal": LEGAL_SCHEMA,
    "procurement": PROCUREMENT_SCHEMA,
    "healthcare": HEALTHCARE_SCHEMA,
}

def get_domain_schema(domain: str) -> Dict[str, Any]:
    schema = ALL_DOMAIN_SCHEMAS.get(domain.lower())
    if not schema:
        raise ValueError(f"Domain schema for '{domain}' not found.")
    return schema

def get_all_schemas() -> Dict[str, Any]:
    return ALL_DOMAIN_SCHEMAS

def generate_extraction_prompt(domain: str, text: str) -> str:
    schema = get_domain_schema(domain)
    entity_labels = [e["label"] for e in schema["entities"]]
    relationship_labels = [r["type"] for r in schema["relationships"]]

    prompt = f"""
Extract entities and relationships from the text according to the {domain} schema.

Entities: {', '.join(entity_labels)}
Relationships: {', '.join(relationship_labels)}

Return a JSON object with:
- "entities": list of objects, each with a "label" and its properties.
- "relationships": list of objects, each with "from", "to", "type", and optional "properties".

Text: \"\"\"{text}\"\"\"
"""
    return prompt


if __name__ == "__main__":
    print("--- Personal Assistance Schema ---")
    print(json.dumps(get_domain_schema("personal_assistance"), indent=2))