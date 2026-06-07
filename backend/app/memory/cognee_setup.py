import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import structlog

# Qdrant Client
from qdrant_client import QdrantClient, models

# KuzuDB Client
import kuzu

# OpenAI for Embeddings and LLM for Entity Extraction
from openai import AsyncOpenAI # Or your preferred LLM client

# Local imports
from app.memory.graph_setup import KuzuGraph
from app.memory.legal_schema import LEGAL_SCHEMA

logger = structlog.get_logger("aether.memory.cognee_setup")

class CogneeMemory:
    """Orchestrates memory operations: ingestion, embedding, vector store (Qdrant), and graph store (KuzuDB) interaction."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._initialized = False
        
        self.qdrant_client: Optional[QdrantClient] = None
        self.kuzu_graph: Optional[KuzuGraph] = None
        self.openai_client: Optional[AsyncOpenAI] = None

        self.qdrant_collection_name = self.config.get("qdrant_collection_name", "aether_memory")
        self.embedding_model_name = self.config.get("embedding_model_name", "text-embedding-ada-002")
        self.llm_extraction_model_name = self.config.get("llm_extraction_model_name", "gpt-4o-mini") # For entity extraction
        self.embedding_dim = self.config.get("embedding_dim", 1536) # Default for text-embedding-ada-002

    async def initialize(self):
        """Connects to Qdrant, KuzuDB, and initializes LLM clients, setting up schemas."""
        if self._initialized:
            logger.info("cognee_memory.already_initialized")
            return

        logger.info("cognee_memory.initializing")
        try:
            # Initialize Qdrant Client
            self.qdrant_client = QdrantClient(host=self.config.get("qdrant_host", "localhost"), port=self.config.get("qdrant_port", 6333))
            # Ensure collection exists
            self.qdrant_client.recreate_collection(
                collection_name=self.qdrant_collection_name,
                vectors_config=models.VectorParams(size=self.embedding_dim, distance=models.Distance.COSINE)
            )
            logger.info("qdrant.client_initialized", collection=self.qdrant_collection_name)

            # Initialize KuzuDB Graph
            kuzu_db_path = self.config.get("kuzu_db_path", "/tmp/aether/kuzu.db")
            self.kuzu_graph = KuzuGraph(db_path=kuzu_db_path)
            self.kuzu_graph.initialize() # This will create schema based on LEGAL_SCHEMA
            logger.info("kuzu_graph.initialized", db_path=kuzu_db_path)

            # Initialize OpenAI Client (for embeddings and entity extraction)
            self.openai_client = AsyncOpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
                base_url=os.environ.get("OPENAI_API_BASE") # Use custom base_url if configured
            )
            logger.info("openai.client_initialized")

            self._initialized = True
            logger.info("cognee_memory.initialized_success")
        except Exception as e:
            logger.error("cognee_memory.initialization_failed", error=str(e), exc_info=True)
            raise

    async def ingest(self, event: Dict[str, Any]):
        """Ingests an event, generates embeddings, extracts entities/relationships, and updates vector + graph stores."""
        if not self._initialized:
            await self.initialize()

        content = event.get("content", "")
        if not content:
            logger.warning("cognee_memory.ingest_empty_content", event_id=event.get("event_id"))
            return

        event_id = event.get("event_id", str(uuid.uuid4()))
        timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())
        source = event.get("source", "unknown")

        logger.info("cognee_memory.ingesting_event", event_id=event_id, content_len=len(content), source=source)

        try:
            # 1. Generate embeddings for the content
            embedding_response = await self.openai_client.embeddings.create(
                input=content,
                model=self.embedding_model_name
            )
            embedding = embedding_response.data[0].embedding
            logger.debug("cognee_memory.embedding_generated", event_id=event_id)

            # 2. Store in Qdrant (vector store)
            qdrant_point = models.PointStruct(
                id=str(uuid.UUID(event_id)), # Qdrant expects UUID or int for ID
                vector=embedding,
                payload={
                    "content": content,
                    "timestamp": timestamp,
                    "source": source,
                    "event_id": event_id # Store original event_id as payload for retrieval
                }
            )
            operation_info = self.qdrant_client.upsert(
                collection_name=self.qdrant_collection_name,
                points=[qdrant_point],
                wait=True
            )
            logger.debug("qdrant.upsert_complete", event_id=event_id, status=operation_info.status.name)

            # 3. Extract entities and relationships using LLM
            extracted_data = await self._extract_entities_and_relationships_llm(content)
            entities = extracted_data.get("entities", [])
            relationships = extracted_data.get("relationships", [])
            logger.debug("cognee_memory.llm_extraction_complete", event_id=event_id, entities_count=len(entities), relationships_count=len(relationships))

            # 4. Store in KuzuDB (graph store)
            await self._update_kuzu_graph(event_id, content, entities, relationships, timestamp)

            logger.info("cognee_memory.ingestion_complete", event_id=event_id, entities_count=len(entities), relationships_count=len(relationships))
        except Exception as e:
            logger.error("cognee_memory.ingestion_failed", event_id=event_id, error=str(e), exc_info=True)
            raise

    async def _extract_entities_and_relationships_llm(self, text: str) -> Dict[str, Any]:
        """Extracts entities and relationships from text using an LLM, guided by LEGAL_SCHEMA."""
        schema_description = json.dumps(LEGAL_SCHEMA, indent=2)
        prompt = f"""You are an expert knowledge graph extractor. Your task is to identify entities and relationships from the provided text based on the following schema. 
        Extract only entities and relationships explicitly defined in the schema. If an entity or relationship type is not in the schema, do not extract it.
        
        Schema:
        ```json
        {schema_description}
        ```

        Text to analyze:
        """{text}"""

        Output your response as a JSON object with two keys: "entities" (a list of objects, each with "type", "id", and "properties") and "relationships" (a list of objects, each with "type", "source_id", "target_id", and "properties").
        For entity IDs, use a stable identifier from the text if available (e.g., case number, document ID), otherwise generate a UUID. Ensure IDs are unique within their type.
        Example Entity: {{
        "type": "Case", "id": "CASE-2023-001", "properties": {"case_number": "CASE-2023-001", "status": "Open"}}
        Example Relationship: {"type": "HAS_DOCUMENT", "source_id": "CASE-2023-001", "target_id": "DOC-456", "properties": {"filed_date": "2023-01-15"}}
        """

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.llm_extraction_model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that extracts structured data from text."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1 # Keep it deterministic for extraction
            )
            content = response.choices[0].message.content
            if content:
                return json.loads(content)
            return {"entities": [], "relationships": []}
        except Exception as e:
            logger.error("cognee_memory.llm_extraction_failed", error=str(e), exc_info=True)
            return {"entities": [], "relationships": []}

    async def _update_kuzu_graph(self, event_id: str, content: str, entities: List[Dict[str, Any]], relationships: List[Dict[str, Any]], timestamp: str):
        """Updates the KuzuDB graph with extracted entities and relationships, including temporal metadata."""
        if not self.kuzu_graph:
            logger.error("kuzu_graph.not_initialized_for_update")
            return

        # Add a node for the ingested document/event itself
        doc_id = f"DOC-{event_id}"
        self.kuzu_graph.add_node(
            label="Document",
            properties={
                "id": doc_id,
                "content_summary": content[:200], # Store a summary
                "full_content_qdrant_id": str(uuid.UUID(event_id)), # Link to Qdrant vector
                "timestamp": timestamp,
                "valid_from": timestamp, # Temporal metadata for the document itself
                "valid_to": datetime.max.replace(tzinfo=timezone.utc).isoformat()
            }
        )

        # Add extracted entities
        for entity in entities:
            entity_type = entity.get("type")
            entity_id = entity.get("id")
            properties = entity.get("properties", {})
            if entity_type and entity_id:
                # Ensure temporal properties are set for entities
                properties["valid_from"] = properties.get("valid_from", timestamp)
                properties["valid_to"] = properties.get("valid_to", datetime.max.replace(tzinfo=timezone.utc).isoformat())
                self.kuzu_graph.add_node(label=entity_type, properties=properties)
                # Link document to entities it contains
                self.kuzu_graph.add_edge(from_label="Document", from_id=doc_id, to_label=entity_type, to_id=entity_id, rel_type="CONTAINS_ENTITY")

        # Add extracted relationships
        for rel in relationships:
            rel_type = rel.get("type")
            source_id = rel.get("source_id")
            target_id = rel.get("target_id")
            properties = rel.get("properties", {})
            if rel_type and source_id and target_id:
                # Ensure temporal properties are set for relationships
                properties["valid_from"] = properties.get("valid_from", timestamp)
                properties["valid_to"] = properties.get("valid_to", datetime.max.replace(tzinfo=timezone.utc).isoformat())
                # Need to infer source/target labels from schema or by querying Kuzu
                # For simplicity, assuming source/target IDs directly map to node IDs and labels are known
                # A more robust solution would query Kuzu for node labels based on IDs
                source_label = self._get_entity_label_from_id(source_id) # Helper needed
                target_label = self._get_entity_label_from_id(target_id) # Helper needed
                if source_label and target_label:
                    self.kuzu_graph.add_edge(from_label=source_label, from_id=source_id, to_label=target_label, to_id=target_id, rel_type=rel_type, properties=properties)
                else:
                    logger.warning("cognee_memory.cannot_infer_labels", source_id=source_id, target_id=target_id, rel_type=rel_type)

    def _get_entity_label_from_id(self, entity_id: str) -> Optional[str]:
        """Helper to infer entity label from its ID, potentially by querying Kuzu or checking schema."""
        # This is a simplification. In a real system, you might query KuzuDB
        # or maintain a mapping of ID patterns to labels.
        for label, schema_def in LEGAL_SCHEMA["entities"].items():
            # Simple heuristic: if ID contains a known entity type prefix
            if label.upper() in entity_id.upper():
                return label
        # Fallback if not found, or query KuzuDB: MATCH (n) WHERE n.id = 'entity_id' RETURN labels(n)
        return None

    async def search(self, query: str, mode: str = "semantic", top_k: int = 5, 
                     entity_id: Optional[str] = None, property_name: Optional[str] = None, 
                     query_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Performs semantic, graph, or temporal memory retrieval."""
        if not self._initialized:
            await self.initialize()

        if mode == "semantic":
            query_embedding_response = await self.openai_client.embeddings.create(
                input=query,
                model=self.embedding_model_name
            )
            query_embedding = query_embedding_response.data[0].embedding
            
            search_result = self.qdrant_client.search(
                collection_name=self.qdrant_collection_name,
                query_vector=query_embedding,
                limit=top_k,
                with_payload=True # Retrieve original content and metadata
            )
            return {"mode": "semantic", "query": query, "results": [hit.payload for hit in search_result]}
        
        elif mode == "graph":
            # Assuming query is a Cypher query string
            if not self.kuzu_graph:
                raise ValueError("KuzuGraph not initialized for graph query.")
            results = self.kuzu_graph.query(query)
            return {"mode": "graph", "query": query, "results": results}
        
        elif mode == "temporal":
            if not entity_id or not property_name or not query_time:
                raise ValueError("entity_id, property_name, and query_time are required for temporal mode.")
            if not self.kuzu_graph:
                raise ValueError("KuzuGraph not initialized for temporal query.")
            
            temporal_graph = TemporalGraph(self.kuzu_graph) # Instantiate TemporalGraph with initialized KuzuGraph
            result = await temporal_graph.query_at_time(entity_id, property_name, query_time)
            return {"mode": "temporal", "entity_id": entity_id, "property_name": property_name, "query_time": query_time.isoformat(), "result": result}
        
        else:
            raise ValueError(f"Unsupported memory retrieval mode: {mode}")