"""Legal Schema — Phase 1 (SCAFFOLD)

Vertical knowledge graph schema for South African legal practice.
10–15 entity types, domain-aware out of the box.
"""

LEGAL_SCHEMA = {
    "entities": {
        "Case": {
            "properties": ["case_number", "court", "judge", "parties", "status", "filing_date"],
            "relationships": {
                "heard_at": "Court",
                "involves": "Client",
                "has_document": "Document",
                "subject_to": "Regulation"
            }
        },
        "Court": {
            "properties": ["name", "jurisdiction", "rules", "filing_deadlines"],
            "relationships": {}
        },
        "Judgment": {
            "properties": ["citations", "legal_principles", "outcomes", "date"],
            "relationships": {
                "overturns": "Case",
                "cites": "Judgment"
            }
        },
        "Client": {
            "properties": ["contact_details", "matter_history", "billing_status"],
            "relationships": {}
        },
        "Document": {
            "properties": ["type", "filing_date", "content_hash", "status"],
            "relationships": {
                "belongs_to": "Case"
            }
        },
        "Regulation": {
            "properties": ["act_name", "sections", "compliance_deadlines"],
            "relationships": {
                "applies_to": "Case"
            }
        }
    },
    "indexes": ["Case.case_number", "Court.name", "Document.content_hash"]
}

# TODO: Add schema validation, entity extraction prompts, relationship inference rules.
