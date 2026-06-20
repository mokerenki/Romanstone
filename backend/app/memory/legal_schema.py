LEGAL_SCHEMA = {
    "entities": {
        "Case": {
            "properties": {
                "case_number": "STRING",
                "title": "STRING",
                "status": "STRING",
                "jurisdiction": "STRING",
                "filing_date": "STRING", # ISO date string
            },
            "relationships": {
                "HAS_PARTY": {"target_type": "Party", "properties": {"role": "STRING"}},
                "HAS_DOCUMENT": {"target_type": "Document", "properties": {"relation_type": "STRING"}},
                "RELATES_TO_LAW": {"target_type": "Law", "properties": {}},
            }
        },
        "Party": {
            "properties": {
                "name": "STRING",
                "type": "STRING", # e.g., "Plaintiff", "Defendant", "Witness"
                "organization": "STRING",
            },
            "relationships": {
                "REPRESENTS": {"target_type": "Party", "properties": {}},
                "HAS_CONTACT": {"target_type": "ContactInfo", "properties": {}},
            }
        },
        "Document": {
            "properties": {
                "document_id": "STRING",
                "title": "STRING",
                "type": "STRING", # e.g., "Complaint", "Contract", "Medical Record"
                "author": "STRING",
                "creation_date": "STRING",
                "summary": "STRING",
            },
            "relationships": {
                "REFERENCES": {"target_type": "Document", "properties": {}},
                "MENTIONS": {"target_type": "Person", "properties": {}},
            }
        },
        "Law": {
            "properties": {
                "law_id": "STRING",
                "name": "STRING",
                "jurisdiction": "STRING",
                "effective_date": "STRING",
            },
            "relationships": {
                "AMENDS": {"target_type": "Law", "properties": {}},
            }
        },
        "Person": {
            "properties": {
                "name": "STRING",
                "date_of_birth": "STRING",
                "gender": "STRING",
            },
            "relationships": {
                "WORKS_FOR": {"target_type": "Organization", "properties": {}},
            }
        },
        "Organization": {
            "properties": {
                "name": "STRING",
                "type": "STRING",
            },
            "relationships": {
                "HAS_OFFICE": {"target_type": "Location", "properties": {}},
            }
        },
        "Location": {
            "properties": {
                "address": "STRING",
                "city": "STRING",
                "state": "STRING",
                "zip_code": "STRING",
            },
            "relationships": {}
        },
        # Add more entities as needed for procurements, healthcare, personal assistance
    }
}