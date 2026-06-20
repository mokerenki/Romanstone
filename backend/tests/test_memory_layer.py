"""
Tests for the memory layer stabilization.

Groups:
1. Kuzu DDL builder — pure functions, no DB needed.
2. CogneeMemory.initialize() smoke — real tmp KuzuDB, mocked Qdrant + OpenAI.
3. Per-mode search() validation — ValueError raised before any client is called.

All tests run without Qdrant, OpenAI, or any external service.
"""
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.memory.graph_setup import build_node_ddl, build_rel_ddl, KuzuGraph
from app.memory.cognee_setup import CogneeMemory


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Kuzu DDL builder — unit tests (pure functions, zero I/O)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildNodeDdl:
    """build_node_ddl() generates valid, double-comma-free CREATE NODE TABLE DDL."""

    def test_normal_properties(self):
        ddl = build_node_ddl("Case", {"case_number": "STRING", "status": "STRING"})
        assert ddl.startswith("CREATE NODE TABLE `Case`(")
        assert "id STRING" in ddl
        assert "case_number STRING" in ddl
        assert "status STRING" in ddl
        assert "valid_from STRING" in ddl
        assert "valid_to STRING" in ddl
        assert "PRIMARY KEY (id)" in ddl
        # No double commas
        assert ",," not in ddl.replace(" ", "")

    def test_empty_properties_no_double_comma(self):
        """Regression: empty properties dict must not produce ', , valid_from' double comma."""
        ddl = build_node_ddl("Location", {})
        assert "CREATE NODE TABLE `Location`(" in ddl
        assert "id STRING" in ddl
        assert "valid_from STRING" in ddl
        assert ",," not in ddl.replace(" ", "")

    def test_single_property(self):
        ddl = build_node_ddl("Law", {"name": "STRING"})
        assert "name STRING" in ddl
        assert "valid_from STRING" in ddl
        assert "PRIMARY KEY (id)" in ddl
        assert ",," not in ddl.replace(" ", "")

    def test_temporal_columns_always_appended(self):
        """valid_from and valid_to must be present regardless of user-defined properties."""
        for props in [{}, {"x": "STRING"}, {"a": "STRING", "b": "INT64"}]:
            ddl = build_node_ddl("Foo", props)
            assert "valid_from STRING" in ddl
            assert "valid_to STRING" in ddl


class TestBuildRelDdl:
    """build_rel_ddl() generates valid CREATE REL TABLE DDL."""

    def test_with_properties(self):
        ddl = build_rel_ddl("HAS_PARTY", "Case", "Party", {"role": "STRING"})
        assert "CREATE REL TABLE `HAS_PARTY`" in ddl
        assert "FROM `Case` TO `Party`" in ddl
        assert "role STRING" in ddl
        assert "valid_from STRING" in ddl
        assert "valid_to STRING" in ddl
        assert ",," not in ddl.replace(" ", "")

    def test_empty_properties(self):
        ddl = build_rel_ddl("AMENDS", "Law", "Law", {})
        assert "FROM `Law` TO `Law`" in ddl
        assert "valid_from STRING" in ddl
        assert ",," not in ddl.replace(" ", "")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. KuzuGraph schema creation — real tmp DB
# ═══════════════════════════════════════════════════════════════════════════════

class TestKuzuGraphSchema:
    """KuzuGraph.initialize() runs generated DDL against a real embedded DB."""

    def test_schema_creation_succeeds(self, tmp_path):
        """The full LEGAL_SCHEMA DDL must execute without errors on a fresh DB."""
        db_path = str(tmp_path / "test.db")
        graph = KuzuGraph(db_path=db_path)
        # Should not raise
        graph.initialize()
        assert graph.conn is not None

    def test_schema_creation_idempotent(self, tmp_path):
        """Calling initialize() twice must not raise (tables already exist)."""
        db_path = str(tmp_path / "test.db")
        graph = KuzuGraph(db_path=db_path)
        graph.initialize()
        # Second call — conn already set, returns early
        graph.initialize()
        assert graph.conn is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CogneeMemory.initialize() smoke — real Kuzu, mocked Qdrant + OpenAI
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cognee_initialize_smoke(tmp_path):
    """
    CogneeMemory.initialize() completes successfully when:
    - KuzuDB uses a real tmp directory (embedded, no service needed)
    - Qdrant is mocked (no running Qdrant instance required)
    - OpenAI is mocked (no API key required)
    """
    db_path = str(tmp_path / "kuzu.db")
    memory = CogneeMemory(config={
        "kuzu_db_path": db_path,
        "qdrant_host": "localhost",
        "qdrant_port": 6333,
    })

    # Mock Qdrant: collection doesn't exist → create it
    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists.return_value = False
    mock_qdrant.create_collection.return_value = None

    # Mock OpenAI: just needs to be instantiable
    mock_openai = MagicMock()

    with patch.object(memory, "_init_qdrant", side_effect=lambda: setattr(memory, "qdrant_client", mock_qdrant)), \
         patch.object(memory, "_init_openai", side_effect=lambda: setattr(memory, "openai_client", mock_openai)):
        await memory.initialize()

    assert memory._initialized is True
    assert memory.kuzu_graph is not None          # real KuzuDB was initialised
    assert memory.qdrant_client is mock_qdrant    # mock was injected
    assert memory.openai_client is mock_openai    # mock was injected


@pytest.mark.asyncio
async def test_cognee_initialize_idempotent(tmp_path):
    """Calling initialize() a second time must be a no-op (already initialized guard)."""
    db_path = str(tmp_path / "kuzu.db")
    memory = CogneeMemory(config={"kuzu_db_path": db_path})

    mock_qdrant = MagicMock()
    mock_qdrant.collection_exists.return_value = True

    call_count = {"n": 0}

    def counting_init_qdrant():
        call_count["n"] += 1
        memory.qdrant_client = mock_qdrant

    with patch.object(memory, "_init_qdrant", side_effect=counting_init_qdrant), \
         patch.object(memory, "_init_openai", side_effect=lambda: setattr(memory, "openai_client", MagicMock())):
        await memory.initialize()
        await memory.initialize()  # second call — must be no-op

    assert call_count["n"] == 1, "initialize() must only run once"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Per-mode search() validation
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_semantic_search_rejects_empty_query(tmp_path):
    """search(mode='semantic') raises ValueError before touching Qdrant."""
    memory = CogneeMemory(config={"kuzu_db_path": str(tmp_path / "kuzu.db")})
    memory._initialized = True  # Skip initialize()
    memory.qdrant_client = MagicMock()
    memory.openai_client = MagicMock()

    with pytest.raises(ValueError, match="non-empty"):
        await memory.search(query="   ", mode="semantic")

    # Qdrant must NOT have been called
    memory.qdrant_client.search.assert_not_called()


@pytest.mark.asyncio
async def test_graph_search_rejects_empty_query(tmp_path):
    """search(mode='graph') raises ValueError before touching KuzuDB."""
    memory = CogneeMemory(config={"kuzu_db_path": str(tmp_path / "kuzu.db")})
    memory._initialized = True
    memory.kuzu_graph = MagicMock()

    with pytest.raises(ValueError, match="non-empty"):
        await memory.search(query="", mode="graph")

    memory.kuzu_graph.query.assert_not_called()


@pytest.mark.asyncio
async def test_temporal_search_rejects_missing_fields(tmp_path):
    """search(mode='temporal') raises ValueError when required fields are absent."""
    memory = CogneeMemory(config={"kuzu_db_path": str(tmp_path / "kuzu.db")})
    memory._initialized = True
    memory.kuzu_graph = MagicMock()

    # Missing entity_label
    with pytest.raises(ValueError, match="entity_label"):
        await memory.search(
            query="status", mode="temporal",
            entity_id="CASE-001", query_time="2024-01-01T00:00:00Z",
        )

    # Missing entity_id
    with pytest.raises(ValueError, match="entity_id"):
        await memory.search(
            query="status", mode="temporal",
            entity_label="Case", query_time="2024-01-01T00:00:00Z",
        )

    # Missing query_time
    with pytest.raises(ValueError, match="query_time"):
        await memory.search(
            query="status", mode="temporal",
            entity_label="Case", entity_id="CASE-001",
        )

    # Bad ISO 8601 string
    with pytest.raises(ValueError, match="Invalid query_time"):
        await memory.search(
            query="status", mode="temporal",
            entity_label="Case", entity_id="CASE-001",
            query_time="not-a-date",
        )

    memory.kuzu_graph.query.assert_not_called()


@pytest.mark.asyncio
async def test_unsupported_mode_raises(tmp_path):
    """search() raises ValueError for any unrecognised mode string."""
    memory = CogneeMemory(config={"kuzu_db_path": str(tmp_path / "kuzu.db")})
    memory._initialized = True

    with pytest.raises(ValueError, match="Unsupported memory retrieval mode"):
        await memory.search(query="anything", mode="magic")
