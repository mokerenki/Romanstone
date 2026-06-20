import kuzu
from typing import Any, Dict, List, Optional
import structlog
import os
import json

from app.memory.legal_schema import LEGAL_SCHEMA

logger = structlog.get_logger("aether.memory.graph_setup")

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
            # Ensure the directory exists
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self.db = kuzu.Database(self.db_path)
            self.conn = kuzu.Connection(self.db)
            self._create_schema()
            logger.info("kuzu_graph.connected_and_schema_created")
        except Exception as e:
            logger.error("kuzu_graph.initialization_failed", db_path=self.db_path, error=str(e), exc_info=True)
            raise

    def _create_schema(self):
        """Creates nodes and relationships based on the LEGAL_SCHEMA, handling existing tables gracefully."""
        if not LEGAL_SCHEMA or "entities" not in LEGAL_SCHEMA:
            logger.warning("kuzu_graph.no_legal_schema_defined_or_invalid")
            return

        # Create Node Tables
        for entity_type, entity_def in LEGAL_SCHEMA["entities"].items():
            properties_str = ", ".join([f"{prop} {dtype}" for prop, dtype in entity_def.get("properties", {}).items()])
            # Add temporal properties to all nodes by default
            properties_str += ", valid_from STRING, valid_to STRING"
            
            create_node_query = f"CREATE NODE TABLE {entity_type}(id STRING, {properties_str}, PRIMARY KEY (id))"
            try:
                self.conn.execute(create_node_query)
                logger.info("kuzu_graph.node_table_created", table=entity_type)
            except kuzu.KuzuException as e:
                if "Node table with name" in str(e) and "already exists" in str(e):
                    logger.info("kuzu_graph.node_table_exists", table=entity_type)
                else:
                    logger.warning("kuzu_graph.node_table_creation_failed", table=entity_type, error=str(e), exc_info=True)

        # Create Relationship Tables
        for entity_type, entity_def in LEGAL_SCHEMA["entities"].items():
            for rel_name, rel_target_def in entity_def.get("relationships", {}).items():
                target_type = rel_target_def.get("target_type")
                rel_properties_str = ", ".join([f"{prop} {dtype}" for prop, dtype in rel_target_def.get("properties", {}).items()])
                # Add temporal properties to all relationships by default
                rel_properties_str += ", valid_from STRING, valid_to STRING"

                create_rel_query = f"CREATE REL TABLE {rel_name}(FROM {entity_type} TO {target_type} PROPERTIES ({rel_properties_str}))"
                try:
                    self.conn.execute(create_rel_query)
                    logger.info("kuzu_graph.rel_table_created", table=rel_name, from_node=entity_type, to_node=target_type)
                except kuzu.KuzuException as e:
                    if "Rel table with name" in str(e) and "already exists" in str(e):
                        logger.info("kuzu_graph.rel_table_exists", table=rel_name)
                    else:
                        logger.warning("kuzu_graph.rel_table_creation_failed", table=rel_name, error=str(e), exc_info=True)

    def add_node(self, label: str, properties: Dict[str, Any]):
        """Adds or updates a node in the graph. Uses MERGE for idempotency."""
        if not self.conn: self.initialize()
        
        # Ensure ID is present and convert properties to string for Kuzu
        node_id = properties.get("id")
        if not node_id:
            logger.error("kuzu_graph.add_node_missing_id", label=label, properties=properties)
            return

        # Kuzu requires properties to be passed as a map literal in the query
        props_for_query = {k: v for k, v in properties.items() if k != "id"} # ID is handled separately
        props_for_query_str = json.dumps(props_for_query)

        # Use MERGE to create if not exists, and SET to update properties
        query = f"MERGE (n:{label} {{id: \'{node_id}\'}}) SET n = json(\'{props_for_query_str}\')"
        try:
            self.conn.execute(query)
            logger.debug("kuzu_graph.node_merged", label=label, id=node_id)
        except Exception as e:
            logger.error("kuzu_graph.node_merge_failed", label=label, id=node_id, error=str(e), exc_info=True)

    def add_edge(self, from_label: str, from_id: str, to_label: str, to_id: str, rel_type: str, properties: Dict[str, Any] = None):
        """Adds or updates an edge between two nodes. Uses MERGE for idempotency."""
        if not self.conn: self.initialize()
        
        rel_properties = properties or {}
        rel_props_str = json.dumps(rel_properties)

        # Use MERGE to create if not exists, and SET to update properties
        query = f"MATCH (a:{from_label}), (b:{to_label}) WHERE a.id = \'{from_id}\' AND b.id = \'{to_id}\' MERGE (a)-[r:{rel_type}]->(b) SET r = json(\'{rel_props_str}\')"
        try:
            self.conn.execute(query)
            logger.debug("kuzu_graph.edge_merged", from_id=from_id, to_id=to_id, rel_type=rel_type)
        except Exception as e:
            logger.error("kuzu_graph.edge_merge_failed", from_id=from_id, to_id=to_id, rel_type=rel_type, error=str(e), exc_info=True)

    def query(self, cypher_query: str) -> List[Dict[str, Any]]:
        """Executes a Cypher query and returns results as a list of dictionaries."""
        if not self.conn: self.initialize()
        try:
            response = self.conn.execute(cypher_query)
            results = []
            # Kuzu returns results as a kuzu.query_result.QueryResult object
            # Iterate and convert to list of dicts for easier consumption
            column_names = response.get_column_names()
            for row in response:
                results.append(dict(zip(column_names, row)))
            logger.debug("kuzu_graph.query_executed", query=cypher_query, results_count=len(results))
            return results
        except Exception as e:
            logger.error("kuzu_graph.query_error", query=cypher_query, error=str(e), exc_info=True)
            return []