import asyncio
import json
import hashlib
from app.memory.temporal_setup import TemporalGraph
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
from app.memory.domain_schemas import EXECUTIVE_SCHEMA

# Redis for embedding cache
import redis.asyncio as aioredis

logger = structlog.get_logger("aether.memory.cognee_setup")

EMBEDDING_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


class CogneeMemory:
    """Orchestrates memory operations: ingestion, embedding, vector store (Qdrant), and graph store (KuzuDB) interaction."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._initialized = False
        self._schema = self.config.get("schema", EXECUTIVE_SCHEMA)
        
        self.qdrant_client: Optional[QdrantClient] = None
        self.kuzu_graph: Optional[KuzuGraph] = None
        self.openai_client: Optional[AsyncOpenAI] = None
        self._redis_client: Optional[aioredis.Redis] = None  # <-- NEW

        self.qdrant_collection_name = self.config.get("qdrant_collection_name", "aether_memory")
        self.embedding_model_name = self.config.get(
            "embedding_model_name",
            os.environ.get("OPENAI_EMBEDDING_MODEL", "nvidia/nv-embed-v1")
        )
        self.llm_extraction_model_name = self.config.get(
            "llm_extraction_model_name",
            os.environ.get("OPENAI_CHAT_MODEL", "meta/llama-3.3-70b-instruct")
        )
        self.embedding_dim = self.config.get("embedding_dim", 4096)

    async def initialize(self):
        """Connects to Qdrant, KuzuDB, Redis, and initializes LLM clients, setting up schemas."""
        if self._initialized:
            logger.info("cognee_memory.already_initialized")
            return

        logger.info("cognee_memory.initializing")
        try:
            # Initialize Qdrant Client
            self.qdrant_client = QdrantClient(
                host=self.config.get("qdrant_host", "localhost"),
                port=self.config.get("qdrant_port", 6333)
            )
            self.qdrant_client.recreate_collection(
                collection_name=self.qdrant_collection_name,
                vectors_config=models.VectorParams(size=self.embedding_dim, distance=models.Distance.COSINE)
            )
            logger.info("qdrant.client_initialized", collection=self.qdrant_collection_name)

            # Initialize KuzuDB Graph
            kuzu_db_path = self.config.get("kuzu_db_path", "/tmp/aether/kuzu.db")
            self.kuzu_graph = KuzuGraph(db_path=kuzu_db_path)
            self.kuzu_graph.initialize(schema=self._schema)
            logger.info("kuzu_graph.initialized", db_path=kuzu_db_path)

            # Initialize OpenAI Client
            openai_api_key = os.environ.get("OPENAI_API_KEY")
            if not openai_api_key:
                raise RuntimeError("OPENAI_API_KEY is required for CogneeMemory embeddings and entity extraction.")
            openai_api_base = os.environ.get("OPENAI_API_BASE")
            self.openai_client = AsyncOpenAI(
                api_key=openai_api_key,
                base_url=openai_api_base
            )
            logger.info("openai.client_initialized")

            # Initialize Redis for embedding cache  <-- NEW
            redis_url = self.config.get("redis_url")
            if redis_url:
                self._redis_client = aioredis.from_url(redis_url)
                await self._redis_client.ping()
                logger.info("embedding_cache.redis_connected", redis_url=redis_url)

            self._initialized = True
            logger.info("cognee_memory.initialized_success")
        except Exception as e:
            logger.error("cognee_memory.initialization_failed", error=str(e), exc_info=True)
            raise

    # ── Embedding Cache Helpers ───────────────────────────────────

    def _embedding_cache_key(self, text: str) -> str:
        """Deterministic cache key for an embedding payload."""
        payload = f"{self.embedding_model_name}:{text}"
        return f"aether:embedding:{hashlib.sha256(payload.encode()).hexdigest()}"

    async def _get_cached_embedding(self, text: str) -> Optional[List[float]]:
        """Fetch embedding from Redis cache if available."""
        if not self._redis_client:
            return None
        key = self._embedding_cache_key(text)
        cached = await self._redis_client.get(key)
        if cached:
            logger.debug("embedding_cache.hit", key=key[:16])
            return json.loads(cached)
        return None

    async def _set_cached_embedding(self, text: str, embedding: List[float]) -> None:
        """Store embedding in Redis cache with TTL."""
        if not self._redis_client:
            return
        key = self._embedding_cache_key(text)
        await self._redis_client.setex(
            key,
            EMBEDDING_CACHE_TTL_SECONDS,
            json.dumps(embedding),
        )
        logger.debug("embedding_cache.set", key=key[:16])

    async def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding with caching layer."""
        # 1. Check cache
        cached = await self._get_cached_embedding(text)
        if cached is not None:
            return cached

        # 2. Call API
        embedding_response = await self.openai_client.embeddings.create(
            input=text,
            model=self.embedding_model_name
        )
        embedding = embedding_response.data[0].embedding

        # 3. Store in cache
        await self._set_cached_embedding(text, embedding)
        return embedding

    # ── Ingest ────────────────────────────────────────────────────

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
            # 1. Generate embeddings (with cache)
            embedding = await self._generate_embedding(content)
            logger.debug("cognee_memory.embedding_generated", event_id=event_id)

            # 2. Store in Qdrant
            qdrant_point = models.PointStruct(
                id=str(uuid.UUID(event_id)),
                vector=embedding,
                payload={
                    "content": content,
                    "timestamp": timestamp,
                    "source": source,
                    "event_id": event_id
                }
            )
            operation_info = self.qdrant_client.upsert(
                collection_name=self.qdrant_collection_name,
                points=[qdrant_point],
                wait=True
            )
            logger.debug("qdrant.upsert_complete", event_id=event_id, status=operation_info.status.name)

            # 3. Extract entities and relationships
            extracted_data = await self._extract_entities_and_relationships_llm(content)
            entities = extracted_data.get("entities", [])
            relationships = extracted_data.get("relationships", [])
            logger.debug("cognee_memory.llm_extraction_complete", event_id=event_id, entities_count=len(entities), relationships_count=len(relationships))

            # 4. Store in KuzuDB
            await self._update_kuzu_graph(event_id, content, entities, relationships, timestamp)

            logger.info("cognee_memory.ingestion_complete", event_id=event_id, entities_count=len(entities), relationships_count=len(relationships))
        except Exception as e:
            logger.error("cognee_memory.ingestion_failed", event_id=event_id, error=str(e), exc_info=True)
            raise

    async def _extract_entities_and_relationships_llm(self, text: str) -> Dict[str, Any]:
        """Extracts entities and relationships from text using an LLM, guided by the configured schema."""
        schema_description = json.dumps(self._schema, indent=2)
        prompt = f"""You are an expert knowledge graph extractor. Your task is to identify entities and relationships from the provided text based on the following schema. 
        Extract only entities and relationships explicitly defined in the schema. If an entity or relationship type is not in the schema, do not extract it.
        
        Schema:
        ```json
        {schema_description}
        ```

        Text to analyze:
        {text}

        Output your response as a JSON object with two keys: "entities" (a list of objects, each with "type", "id", and "properties") and "relationships" (a list of objects, each with "type", "source_id", "target_id", and "properties").
        For entity IDs, use a stable identifier from the text if available (e.g., case number, document ID), otherwise generate a UUID. Ensure IDs are unique within their type.
        Example Entity: {{
        "type": "Case", "id": "CASE-2023-001", "properties": {{"case_number": "CASE-2023-001", "status": "Open"}}}}
        Example Relationship: {{"type": "HAS_DOCUMENT", "source_id": "CASE-2023-001", "target_id": "DOC-456", "properties": {{"filed_date": "2023-01-15"}}}}
        """

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.llm_extraction_model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that extracts structured data from text."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
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

        doc_id = f"DOC-{event_id}"
        self.kuzu_graph.add_node(
            label="Document",
            properties={
                "id": doc_id,
                "content_summary": content[:200],
                "full_content_qdrant_id": str(uuid.UUID(event_id)),
                "timestamp": timestamp,
                "valid_from": timestamp,
                "valid_to": datetime.max.replace(tzinfo=timezone.utc).isoformat()
            }
        )

        for entity in entities:
            entity_type = entity.get("type")
            entity_id = entity.get("id")
            properties = entity.get("properties", {})
            if entity_type and entity_id:
                properties["valid_from"] = properties.get("valid_from", timestamp)
                properties["valid_to"] = properties.get("valid_to", datetime.max.replace(tzinfo=timezone.utc).isoformat())
                self.kuzu_graph.add_node(label=entity_type, properties=properties)
                self.kuzu_graph.add_edge(from_label="Document", from_id=doc_id, to_label=entity_type, to_id=entity_id, rel_type="CONTAINS_ENTITY")

        for rel in relationships:
            rel_type = rel.get("type")
            source_id = rel.get("source_id")
            target_id = rel.get("target_id")
            properties = rel.get("properties", {})
            if rel_type and source_id and target_id:
                properties["valid_from"] = properties.get("valid_from", timestamp)
                properties["valid_to"] = properties.get("valid_to", datetime.max.replace(tzinfo=timezone.utc).isoformat())
                source_label = self._get_entity_label_from_id(source_id)
                target_label = self._get_entity_label_from_id(target_id)
                if source_label and target_label:
                    self.kuzu_graph.add_edge(from_label=source_label, from_id=source_id, to_label=target_label, to_id=target_id, rel_type=rel_type, properties=properties)
                else:
                    logger.warning("cognee_memory.cannot_infer_labels", source_id=source_id, target_id=target_id, rel_type=rel_type)

    def _get_entity_label_from_id(self, entity_id: str) -> Optional[str]:
        """Helper to infer entity label from its ID."""
        for entity_name, entity_def in self._schema.get("entities", {}).items():
            if entity_name.upper() in entity_id.upper():
                return entity_name
        return None

    async def search(self, query: str, mode: str = "semantic", top_k: int = 5, 
                     entity_label: Optional[str] = None, entity_id: Optional[str] = None, property_name: Optional[str] = None, 
                     query_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Performs semantic, graph, or temporal memory retrieval."""
        if not self._initialized:
            await self.initialize()

        if mode == "semantic":
            # Use cached embedding for search too
            query_embedding = await self._generate_embedding(query)
            
            search_result = self.qdrant_client.search(
                collection_name=self.qdrant_collection_name,
                query_vector=query_embedding,
                limit=top_k,
                with_payload=True
            )
            return {"mode": "semantic", "query": query, "results": [hit.payload for hit in search_result]}
        
        elif mode == "graph":
            if not self.kuzu_graph:
                raise ValueError("KuzuGraph not initialized for graph query.")
            results = self.kuzu_graph.query(query)
            return {"mode": "graph", "query": query, "results": results}
        
        elif mode == "temporal":
            if not entity_id or not property_name or not query_time:
                raise ValueError("entity_id, property_name, and query_time are required for temporal mode.")
            if not self.kuzu_graph:
                raise ValueError("KuzuGraph not initialized for temporal query.")
            
            temporal_graph = TemporalGraph(self.kuzu_graph)
            result = await temporal_graph.query_at_time(entity_id, property_name, query_time, entity_label=entity_label)
            return {
                "mode": "temporal",
                "entity_label": entity_label,
                "entity_id": entity_id,
                "property_name": property_name,
                "query_time": query_time.isoformat(),
                "result": result,
            }
        
        else:
            raise ValueError(f"Unsupported memory retrieval mode: {mode}")

    async def close(self):
        """Closes all client connections."""
        if self.qdrant_client:
            try:
                self.qdrant_client.close()
            except Exception:
                pass
        if self.kuzu_graph and self.kuzu_graph.conn:
            try:
                self.kuzu_graph.conn.close()
            except Exception:
                pass
        if self.openai_client:
            await self.openai_client.close()
        if self._redis_client:
            await self._redis_client.close()
        self._initialized = False
        logger.info("cognee_memory.closed")