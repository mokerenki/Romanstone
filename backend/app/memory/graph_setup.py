import kuzu
from typing import Any, Dict, List, Optional
import structlog
import os
import json

from app.memory.legal_schema import LEGAL_SCHEMA

logger = structlog.get_logger("aether.memory.graph_setup")


# ── Pure DDL builder functions (no I/O — unit-testable without a running DB) ──

def build_node_ddl(entity_type: str, properties: Dict[str, str]) -> str:
    """
    Build a Kuzu CREATE NODE TABLE DDL string for the given entity type.

    Temporal columns (valid_from, valid_to) are always appended.
    Handles the empty-properties edge case — no double commas.

    Args:
        entity_type: The Kuzu table name (e.g. "Case").
        properties:  Mapping of column name → Kuzu type (e.g. {"title": "STRING"}).

    Returns:
        A valid Kuzu DDL string, e.g.:
        "CREATE NODE TABLE Case(id STRING, title STRING, valid_from STRING, valid_to STRING, PRIMARY KEY (id))"
    """
    parts = [f"{col} {dtype}" for col, dtype in properties.items()]
    parts += ["valid_from STRING", "valid_to STRING"]
    columns = ", ".join(parts)
    return f"CREATE NODE TABLE `{entity_type}`(id STRING, {columns}, PRIMARY KEY (id))"


def build_rel_ddl(
    rel_name: str,
    from_type: str,
    to_type: str,
    properties: Dict[str, str],
) -> str:
    """
    Build a Kuzu CREATE REL TABLE DDL string.

    Temporal columns are always appended to relationship properties too.

    Args:
        rel_name:   The relationship table name (e.g. "HAS_PARTY").
        from_type:  Source node table (e.g. "Case").
        to_type:    Target node table (e.g. "Party").
        properties: Extra relationship properties.

    Returns:
        A valid Kuzu REL TABLE DDL string.
    """
    parts = [f"{col} {dtype}" for col, dtype in properties.items()]
    parts += ["valid_from STRING", "valid_to STRING"]
    props_str = ", ".join(parts)
    return (
        f"CREATE REL TABLE `{rel_name}`"
        f"(FROM `{from_type}` TO `{to_type}` PROPERTIES ({props_str}))"
    )


# ── KuzuGraph —————————————————————————————————————————————————————————————────

class KuzuGraph:
    """Manages the KuzuDB embedded knowledge graph, including schema creation and query execution."""

    def __init__(self, db_path: str = "/tmp/aether/kuzu.db"):
        self.db_path = db_path
        self.db: Optional[kuzu.Database] = None
        self.conn: Optional[kuzu.Connection] = None
        logger.info("kuzu_graph.initialized", db_path=db_path)

    def initialize(self):
        """Initializes the KuzuDB database and creates the schema if not already created."""
        if self.conn:
            logger.info("kuzu_graph.already_initialized")
            return

        logger.info("kuzu_graph.connecting", db_path=self.db_path)
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self.db = kuzu.Database(self.db_path)
            self.conn = kuzu.Connection(self.db)
            self._create_schema()
            logger.info("kuzu_graph.connected_and_schema_created")
        except Exception as e:
            logger.error("kuzu_graph.initialization_failed",
                         db_path=self.db_path, error=str(e), exc_info=True)
            raise

    def _create_schema(self):
        """Creates node and relationship tables from LEGAL_SCHEMA using the pure DDL builders."""
        if not LEGAL_SCHEMA or "entities" not in LEGAL_SCHEMA:
            logger.warning("kuzu_graph.no_legal_schema_defined_or_invalid")
            return

        # ── Node tables ───────────────────────────────────────────────────────
        for entity_type, entity_def in LEGAL_SCHEMA["entities"].items():
            ddl = build_node_ddl(entity_type, entity_def.get("properties", {}))
            try:
                self.conn.execute(ddl)
                logger.info("kuzu_graph.node_table_created", table=entity_type)
            except (RuntimeError, Exception) as e:
                if "already exists" in str(e):
                    logger.info("kuzu_graph.node_table_exists", table=entity_type)
                else:
                    logger.warning("kuzu_graph.node_table_creation_failed",
                                   table=entity_type, error=str(e))

        # ── Relationship tables ───────────────────────────────────────────────
        for entity_type, entity_def in LEGAL_SCHEMA["entities"].items():
            for rel_name, rel_def in entity_def.get("relationships", {}).items():
                target_type = rel_def.get("target_type")
                ddl = build_rel_ddl(
                    rel_name, entity_type, target_type,
                    rel_def.get("properties", {})
                )
                try:
                    self.conn.execute(ddl)
                    logger.info("kuzu_graph.rel_table_created",
                                table=rel_name, from_node=entity_type, to_node=target_type)
                except (RuntimeError, Exception) as e:
                    if "already exists" in str(e):
                        logger.info("kuzu_graph.rel_table_exists", table=rel_name)
                    else:
                        logger.warning("kuzu_graph.rel_table_creation_failed",
                                       table=rel_name, error=str(e))

    def add_node(self, label: str, properties: Dict[str, Any]):
        """Adds or updates a node in the graph. Uses MERGE for idempotency."""
        if not self.conn:
            self.initialize()

        node_id = properties.get("id")
        if not node_id:
            logger.error("kuzu_graph.add_node_missing_id", label=label, properties=properties)
            return

        props_for_query = {k: v for k, v in properties.items() if k != "id"}
        props_for_query_str = json.dumps(props_for_query)

        query = f"MERGE (n:{label} {{id: '{node_id}'}}) SET n = json('{props_for_query_str}')"
        try:
            self.conn.execute(query)
            logger.debug("kuzu_graph.node_merged", label=label, id=node_id)
        except Exception as e:
            logger.error("kuzu_graph.node_merge_failed",
                         label=label, id=node_id, error=str(e), exc_info=True)

    def add_edge(
        self,
        from_label: str,
        from_id: str,
        to_label: str,
        to_id: str,
        rel_type: str,
        properties: Dict[str, Any] = None,
    ):
        """Adds or updates an edge between two nodes. Uses MERGE for idempotency."""
        if not self.conn:
            self.initialize()

        rel_properties = properties or {}
        rel_props_str = json.dumps(rel_properties)

        query = (
            f"MATCH (a:{from_label}), (b:{to_label}) "
            f"WHERE a.id = '{from_id}' AND b.id = '{to_id}' "
            f"MERGE (a)-[r:{rel_type}]->(b) SET r = json('{rel_props_str}')"
        )
        try:
            self.conn.execute(query)
            logger.debug("kuzu_graph.edge_merged",
                         from_id=from_id, to_id=to_id, rel_type=rel_type)
        except Exception as e:
            logger.error("kuzu_graph.edge_merge_failed",
                         from_id=from_id, to_id=to_id, rel_type=rel_type,
                         error=str(e), exc_info=True)

    def query(self, cypher_query: str) -> List[Dict[str, Any]]:
        """Executes a Cypher query and returns results as a list of dictionaries."""
        if not self.conn:
            self.initialize()
        try:
            response = self.conn.execute(cypher_query)
            column_names = response.get_column_names()
            results = [dict(zip(column_names, row)) for row in response]
            logger.debug("kuzu_graph.query_executed",
                         query=cypher_query, results_count=len(results))
            return results
        except Exception as e:
            logger.error("kuzu_graph.query_error",
                         query=cypher_query, error=str(e), exc_info=True)
            return []