import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import structlog

# Qdrant Client
from qdrant_client import QdrantClient, models

# KuzuDB Client
import kuzu

# OpenAI for Embeddings and LLM for Entity Extraction
from openai import AsyncOpenAI

# Local imports
from app.memory.graph_setup import KuzuGraph
from app.memory.legal_schema import LEGAL_SCHEMA

logger = structlog.get_logger("aether.memory.cognee_setup")


class CogneeMemory:
    """
    Orchestrates memory operations: ingestion, embedding, vector store (Qdrant),
    and graph store (KuzuDB) interaction.

    Each external service is initialised in its own ``_init_*`` method so that
    tests can patch individual services without affecting the others.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._initialized = False

        self.qdrant_client: Optional[QdrantClient] = None
        self.kuzu_graph: Optional[KuzuGraph] = None
        self.openai_client: Optional[AsyncOpenAI] = None

        self.qdrant_collection_name = self.config.get("qdrant_collection_name", "aether_memory")
        self.embedding_model_name = self.config.get("embedding_model_name", "text-embedding-ada-002")
        self.llm_extraction_model_name = self.config.get("llm_extraction_model_name", "gpt-4o-mini")
        self.embedding_dim = self.config.get("embedding_dim", 1536)

    # ── Private init helpers (individually mockable) ──────────────────────────

    def _init_qdrant(self):
        """Connect to Qdrant and ensure the collection exists (get-or-create, never destroys data)."""
        self.qdrant_client = QdrantClient(
            host=self.config.get("qdrant_host", "localhost"),
            port=self.config.get("qdrant_port", 6333),
        )
        if not self.qdrant_client.collection_exists(self.qdrant_collection_name):
            self.qdrant_client.create_collection(
                collection_name=self.qdrant_collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedding_dim,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("qdrant.collection_created", collection=self.qdrant_collection_name)
        else:
            logger.info("qdrant.collection_exists", collection=self.qdrant_collection_name)

    def _init_kuzu(self):
        """Connect to KuzuDB and create/verify the schema."""
        kuzu_db_path = self.config.get("kuzu_db_path", "/tmp/aether/kuzu.db")
        self.kuzu_graph = KuzuGraph(db_path=kuzu_db_path)
        self.kuzu_graph.initialize()
        logger.info("kuzu_graph.initialized", db_path=kuzu_db_path)

    def _init_openai(self):
        """Create the AsyncOpenAI client for embeddings and entity extraction."""
        self.openai_client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_API_BASE") or None,
        )
        logger.info("openai.client_initialized")

    # ── Public lifecycle ──────────────────────────────────────────────────────

    async def initialize(self):
        """
        Connect to Qdrant, KuzuDB, and initialise LLM clients.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._initialized:
            logger.info("cognee_memory.already_initialized")
            return

        logger.info("cognee_memory.initializing")
        try:
            self._init_qdrant()
            self._init_kuzu()
            self._init_openai()
            self._initialized = True
            logger.info("cognee_memory.initialized_success")
        except Exception as e:
            logger.error("cognee_memory.initialization_failed", error=str(e), exc_info=True)
            raise

    async def close(self):
        """Release resources."""
        self.qdrant_client = None
        self.kuzu_graph = None
        self.openai_client = None
        self._initialized = False
        logger.info("cognee_memory.closed")

    # ── Ingestion ─────────────────────────────────────────────────────────────

    async def ingest(self, event: Dict[str, Any]):
        """Ingests an event, generates embeddings, extracts entities/relationships, and updates stores."""
        if not self._initialized:
            await self.initialize()

        content = event.get("content", "")
        if not content:
            logger.warning("cognee_memory.ingest_empty_content", event_id=event.get("event_id"))
            return

        event_id = event.get("event_id", str(uuid.uuid4()))
        timestamp = event.get("timestamp", datetime.now(timezone.utc).isoformat())
        source = event.get("source", "unknown")

        logger.info("cognee_memory.ingesting_event",
                    event_id=event_id, content_len=len(content), source=source)

        try:
            # 1. Generate embeddings
            embedding_response = await self.openai_client.embeddings.create(
                input=content,
                model=self.embedding_model_name,
            )
            embedding = embedding_response.data[0].embedding

            # 2. Store in Qdrant
            qdrant_point = models.PointStruct(
                id=str(uuid.UUID(event_id)),
                vector=embedding,
                payload={
                    "content": content,
                    "timestamp": timestamp,
                    "source": source,
                    "event_id": event_id,
                },
            )
            self.qdrant_client.upsert(
                collection_name=self.qdrant_collection_name,
                points=[qdrant_point],
                wait=True,
            )

            # 3. Extract entities / relationships via LLM
            extracted = await self._extract_entities_and_relationships_llm(content)
            entities = extracted.get("entities", [])
            relationships = extracted.get("relationships", [])

            # 4. Store in KuzuDB
            await self._update_kuzu_graph(event_id, content, entities, relationships, timestamp)

            logger.info("cognee_memory.ingestion_complete",
                        event_id=event_id,
                        entities_count=len(entities),
                        relationships_count=len(relationships))
        except Exception as e:
            logger.error("cognee_memory.ingestion_failed",
                         event_id=event_id, error=str(e), exc_info=True)
            raise

    # ── Retrieval ─────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        mode: str = "semantic",
        top_k: int = 5,
        entity_label: Optional[str] = None,
        entity_id: Optional[str] = None,
        property_name: Optional[str] = None,
        query_time=None,
    ) -> Dict[str, Any]:
        """
        Performs semantic, graph, or temporal memory retrieval.

        Each mode validates its own required inputs before touching any client,
        so callers get a clear ValueError instead of a cryptic client error.
        """
        if not self._initialized:
            await self.initialize()

        if mode == "semantic":
            # ── Semantic: vector similarity search ────────────────────────────
            if not query or not query.strip():
                raise ValueError("semantic mode requires a non-empty 'query' string.")

            embedding_resp = await self.openai_client.embeddings.create(
                input=query,
                model=self.embedding_model_name,
            )
            query_embedding = embedding_resp.data[0].embedding

            hits = self.qdrant_client.search(
                collection_name=self.qdrant_collection_name,
                query_vector=query_embedding,
                limit=top_k,
                with_payload=True,
            )
            return {"mode": "semantic", "query": query, "results": [h.payload for h in hits]}

        elif mode == "graph":
            # ── Graph: raw Cypher query ───────────────────────────────────────
            if not query or not query.strip():
                raise ValueError("graph mode requires a non-empty Cypher 'query' string.")
            if not self.kuzu_graph:
                raise ValueError("KuzuGraph not initialized for graph query.")

            results = self.kuzu_graph.query(query)
            return {"mode": "graph", "query": query, "results": results}

        elif mode == "temporal":
            # ── Temporal: property value at a point in time ───────────────────
            if not query or not query.strip():
                raise ValueError("temporal mode requires 'query' (the property name).")
            if not entity_label:
                raise ValueError("temporal mode requires 'entity_label'.")
            if not entity_id:
                raise ValueError("temporal mode requires 'entity_id'.")
            if query_time is None:
                raise ValueError("temporal mode requires 'query_time' (datetime or ISO string).")

            # Normalise query_time to a datetime object if it arrived as a string
            if isinstance(query_time, str):
                try:
                    query_time = datetime.fromisoformat(query_time.replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError(
                        f"Invalid query_time '{query_time}'. Must be ISO 8601 (e.g. 2023-10-27T10:00:00Z)."
                    )

            if not self.kuzu_graph:
                raise ValueError("KuzuGraph not initialized for temporal query.")

            from app.memory.temporal_setup import TemporalGraph
            temporal_graph = TemporalGraph(self.kuzu_graph)
            result = await temporal_graph.query_at_time(
                entity_id, query, query_time, entity_label=entity_label
            )
            return {
                "mode": "temporal",
                "entity_label": entity_label,
                "entity_id": entity_id,
                "property_name": query,
                "query_time": query_time.isoformat(),
                "result": result,
            }

        else:
            raise ValueError(
                f"Unsupported memory retrieval mode: '{mode}'. "
                "Must be one of: 'semantic', 'graph', 'temporal'."
            )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _extract_entities_and_relationships_llm(self, text: str) -> Dict[str, Any]:
        """Extracts entities and relationships from text using an LLM, guided by LEGAL_SCHEMA."""
        schema_description = json.dumps(LEGAL_SCHEMA, indent=2)
        prompt = f"""You are an expert knowledge graph extractor. Your task is to identify entities and relationships from the provided text based on the following schema.
Extract only entities and relationships explicitly defined in the schema.

Schema:
```json
{schema_description}
```

Text to analyze:
{text}

Output a JSON object with two keys: "entities" (list of objects with "type", "id", "properties") and "relationships" (list of objects with "type", "source_id", "target_id", "properties").
"""
        try:
            response = await self.openai_client.chat.completions.create(
                model=self.llm_extraction_model_name,
                messages=[
                    {"role": "system", "content": "You extract structured data from text."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            content = response.choices[0].message.content
            if content:
                return json.loads(content)
        except Exception as e:
            logger.error("cognee_memory.llm_extraction_failed", error=str(e), exc_info=True)
        return {"entities": [], "relationships": []}

    async def _update_kuzu_graph(
        self,
        event_id: str,
        content: str,
        entities: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        timestamp: str,
    ):
        """Updates the KuzuDB graph with extracted entities and relationships."""
        if not self.kuzu_graph:
            logger.error("kuzu_graph.not_initialized_for_update")
            return

        doc_id = f"DOC-{event_id}"
        self.kuzu_graph.add_node(
            "Document",
            {
                "id": doc_id,
                "content_summary": content[:200],
                "full_content_qdrant_id": str(uuid.UUID(event_id)),
                "timestamp": timestamp,
                "valid_from": timestamp,
                "valid_to": datetime.max.replace(tzinfo=timezone.utc).isoformat(),
            },
        )

        for entity in entities:
            entity_type = entity.get("type")
            entity_id = entity.get("id")
            properties = entity.get("properties", {})
            if entity_type and entity_id:
                properties.setdefault("valid_from", timestamp)
                properties.setdefault("valid_to", datetime.max.replace(tzinfo=timezone.utc).isoformat())
                self.kuzu_graph.add_node(label=entity_type, properties={"id": entity_id, **properties})
                self.kuzu_graph.add_edge("Document", doc_id, entity_type, entity_id, "CONTAINS_ENTITY")

        for rel in relationships:
            rel_type = rel.get("type")
            source_id = rel.get("source_id")
            target_id = rel.get("target_id")
            properties = rel.get("properties", {})
            if rel_type and source_id and target_id:
                properties.setdefault("valid_from", timestamp)
                properties.setdefault("valid_to", datetime.max.replace(tzinfo=timezone.utc).isoformat())
                source_label = self._get_entity_label_from_id(source_id)
                target_label = self._get_entity_label_from_id(target_id)
                if source_label and target_label:
                    self.kuzu_graph.add_edge(
                        source_label, source_id, target_label, target_id,
                        rel_type, properties,
                    )
                else:
                    logger.warning("cognee_memory.cannot_infer_labels",
                                   source_id=source_id, target_id=target_id, rel_type=rel_type)

    def _get_entity_label_from_id(self, entity_id: str) -> Optional[str]:
        """Infer entity label from its ID using a simple schema heuristic."""
        for label in LEGAL_SCHEMA.get("entities", {}):
            if label.upper() in entity_id.upper():
                return label
        return None