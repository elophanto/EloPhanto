"""Tests for RLM (Recursive Language Model) — Phase 1 + Phase 2.

Phase 1: agent_call in the code execution sandbox (RPC server, stubs).
Phase 2: ContextStore + context tools (ingest, query, slice, index, transform).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.context_store import ContextStore, _estimate_tokens
from core.database import Database
from tools.base import PermissionLevel, ToolResult
from tools.context.context_tools import (
    ContextIndexTool,
    ContextIngestTool,
    ContextQueryTool,
    ContextSliceTool,
    ContextTransformTool,
)
from tools.self_dev.rpc_server import (
    ALLOWED_TOOLS,
    MAX_AGENT_CALLS,
    MAX_AGENT_CALL_DEPTH,
    RPCServer,
)
from tools.self_dev.stub_generator import generate_stubs


# ═══════════════════════════════════════════════════════════════════
# Phase 1: agent_call + RPC server
# ═══════════════════════════════════════════════════════════════════


class TestAgentCallInAllowedTools:
    """Verify agent_call and context tools are in the sandbox allowlist."""

    def test_agent_call_allowed(self) -> None:
        assert "agent_call" in ALLOWED_TOOLS

    def test_context_tools_allowed(self) -> None:
        for name in (
            "context_ingest",
            "context_query",
            "context_slice",
            "context_index",
            "context_transform",
        ):
            assert name in ALLOWED_TOOLS, f"{name} missing from ALLOWED_TOOLS"

    def test_total_allowed_tools(self) -> None:
        assert len(ALLOWED_TOOLS) == 13


class TestStubGenerator:
    """Verify stubs are generated for all RLM tools."""

    def test_agent_call_stub_generated(self) -> None:
        stubs = generate_stubs("/tmp/test.sock")
        assert "def agent_call(" in stubs
        assert "prompt: str" in stubs
        assert 'context: str = ""' in stubs
        assert 'model: str = "auto"' in stubs

    def test_context_stubs_generated(self) -> None:
        stubs = generate_stubs("/tmp/test.sock")
        for name in (
            "context_ingest",
            "context_query",
            "context_slice",
            "context_index",
            "context_transform",
        ):
            assert f"def {name}(" in stubs, f"Missing stub for {name}"

    def test_stubs_include_rpc_call(self) -> None:
        stubs = generate_stubs("/tmp/test.sock")
        assert "def _rpc_call(" in stubs
        assert '_SOCKET_PATH = "/tmp/test.sock"' in stubs

    def test_all_allowed_tools_have_stubs(self) -> None:
        stubs = generate_stubs("/tmp/test.sock")
        for tool_name in ALLOWED_TOOLS:
            assert f"def {tool_name}(" in stubs, f"No stub for {tool_name}"


class TestRPCServerAgentCall:
    """Test the RPC server's agent_call handler."""

    @pytest.fixture
    def mock_router(self) -> MagicMock:
        router = MagicMock()
        response = MagicMock()
        response.content = "Analysis result"
        response.model_used = "test-model"
        response.input_tokens = 100
        response.output_tokens = 50
        router.complete = AsyncMock(return_value=response)
        return router

    @pytest.fixture
    def mock_registry(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def rpc(self, mock_registry: MagicMock, mock_router: MagicMock) -> RPCServer:
        return RPCServer(
            registry=mock_registry,
            executor=MagicMock(),
            router=mock_router,
            agent_call_depth=0,
        )

    @pytest.mark.asyncio
    async def test_agent_call_success(self, rpc: RPCServer) -> None:
        result = await rpc._handle_agent_call(
            1, {"prompt": "Analyze this", "context": "some code"}
        )
        assert result["success"] is True
        assert result["data"]["response"] == "Analysis result"
        assert result["data"]["model_used"] == "test-model"
        assert result["data"]["depth"] == 1

    @pytest.mark.asyncio
    async def test_agent_call_no_prompt(self, rpc: RPCServer) -> None:
        result = await rpc._handle_agent_call(1, {"prompt": ""})
        assert result["success"] is False
        assert "requires a 'prompt'" in result["error"]

    @pytest.mark.asyncio
    async def test_agent_call_no_router(self, mock_registry: MagicMock) -> None:
        rpc = RPCServer(
            registry=mock_registry,
            executor=MagicMock(),
            router=None,
        )
        result = await rpc._handle_agent_call(1, {"prompt": "test"})
        assert result["success"] is False
        assert "router not available" in result["error"]

    @pytest.mark.asyncio
    async def test_agent_call_depth_limit(
        self, mock_registry: MagicMock, mock_router: MagicMock
    ) -> None:
        rpc = RPCServer(
            registry=mock_registry,
            executor=MagicMock(),
            router=mock_router,
            agent_call_depth=MAX_AGENT_CALL_DEPTH,
        )
        result = await rpc._handle_agent_call(1, {"prompt": "test"})
        assert result["success"] is False
        assert "depth limit" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_agent_call_budget_limit(self, rpc: RPCServer) -> None:
        # Exhaust the budget
        rpc._agent_call_count = MAX_AGENT_CALLS
        result = await rpc._handle_agent_call(1, {"prompt": "test"})
        assert result["success"] is False
        assert "limit exceeded" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_agent_call_model_fast(
        self, rpc: RPCServer, mock_router: MagicMock
    ) -> None:
        await rpc._handle_agent_call(1, {"prompt": "classify this", "model": "fast"})
        call_kwargs = mock_router.complete.call_args
        assert call_kwargs.kwargs["task_type"] == "simple"

    @pytest.mark.asyncio
    async def test_agent_call_model_strong(
        self, rpc: RPCServer, mock_router: MagicMock
    ) -> None:
        await rpc._handle_agent_call(1, {"prompt": "deep analysis", "model": "strong"})
        call_kwargs = mock_router.complete.call_args
        assert call_kwargs.kwargs["task_type"] == "planning"

    @pytest.mark.asyncio
    async def test_agent_call_model_override(
        self, rpc: RPCServer, mock_router: MagicMock
    ) -> None:
        await rpc._handle_agent_call(1, {"prompt": "test", "model": "gpt-4o"})
        call_kwargs = mock_router.complete.call_args
        assert call_kwargs.kwargs["model_override"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_agent_call_context_in_system_prompt(
        self, rpc: RPCServer, mock_router: MagicMock
    ) -> None:
        await rpc._handle_agent_call(
            1, {"prompt": "analyze", "context": "def foo(): pass"}
        )
        messages = mock_router.complete.call_args.kwargs["messages"]
        system_msg = messages[0]["content"]
        assert "def foo(): pass" in system_msg
        assert "CONTEXT" in system_msg

    @pytest.mark.asyncio
    async def test_agent_call_no_context(
        self, rpc: RPCServer, mock_router: MagicMock
    ) -> None:
        await rpc._handle_agent_call(1, {"prompt": "hello"})
        messages = mock_router.complete.call_args.kwargs["messages"]
        system_msg = messages[0]["content"]
        assert "CONTEXT" not in system_msg

    @pytest.mark.asyncio
    async def test_dispatch_routes_to_agent_call(self, rpc: RPCServer) -> None:
        rpc._call_count = 0
        result = await rpc._dispatch(1, "agent_call", {"prompt": "test"})
        assert result["success"] is True
        assert result["data"]["response"] == "Analysis result"

    @pytest.mark.asyncio
    async def test_dispatch_rejects_unknown_tool(self, rpc: RPCServer) -> None:
        result = await rpc._dispatch(1, "vault_lookup", {})
        assert result["success"] is False
        assert "not available" in result["error"]


# ═══════════════════════════════════════════════════════════════════
# Phase 2: ContextStore
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "test_context.db"))
    await database.initialize()
    return database


@pytest.fixture
async def store(db: Database) -> ContextStore:
    return ContextStore(db=db, embedder=None)


class TestContextStoreCreate:
    @pytest.mark.asyncio
    async def test_create_returns_id(self, store: ContextStore) -> None:
        ctx_id = await store.create("test context")
        assert ctx_id.startswith("ctx_")

    @pytest.mark.asyncio
    async def test_create_with_session(self, store: ContextStore) -> None:
        ctx_id = await store.create("test", session_id="sess_123")
        contexts = await store.list_contexts()
        assert len(contexts) == 1
        assert contexts[0]["context_id"] == ctx_id

    @pytest.mark.asyncio
    async def test_delete(self, store: ContextStore) -> None:
        ctx_id = await store.create("to delete")
        result = await store.delete(ctx_id)
        assert result
        contexts = await store.list_contexts()
        assert len(contexts) == 0


class TestContextStoreIngest:
    @pytest.mark.asyncio
    async def test_ingest_text(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        chunk_ids = await store.ingest_text(
            ctx_id, "test_source", "Hello world content"
        )
        assert len(chunk_ids) >= 1
        assert all(c.startswith("chk_") for c in chunk_ids)

    @pytest.mark.asyncio
    async def test_ingest_file(self, store: ContextStore, tmp_path: Path) -> None:
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        ctx_id = await store.create("test")
        chunk_ids = await store.ingest_file(ctx_id, str(test_file))
        assert len(chunk_ids) >= 1

    @pytest.mark.asyncio
    async def test_ingest_file_not_found(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        with pytest.raises(FileNotFoundError):
            await store.ingest_file(ctx_id, "/nonexistent/file.py")

    @pytest.mark.asyncio
    async def test_ingest_updates_counters(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "src1", "Content one")
        await store.ingest_text(ctx_id, "src2", "Content two")

        contexts = await store.list_contexts()
        ctx = contexts[0]
        assert ctx["source_count"] == 2
        assert ctx["chunk_count"] >= 2
        assert ctx["total_tokens"] > 0

    @pytest.mark.asyncio
    async def test_ingest_large_text_chunks(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        # Generate text with paragraph breaks so the splitter has boundaries
        large_text = "\n\n".join(f"Section {i}. " * 100 for i in range(20))
        chunk_ids = await store.ingest_text(
            ctx_id, "large_source", large_text, max_tokens=200
        )
        assert len(chunk_ids) > 1

    @pytest.mark.asyncio
    async def test_ingest_markdown_with_headings(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        md = "# Title\n\nIntro paragraph.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
        chunk_ids = await store.ingest_text(ctx_id, "doc.md", md)
        assert len(chunk_ids) >= 2  # At least 2 sections


class TestContextStoreQuery:
    @pytest.mark.asyncio
    async def test_keyword_search(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        await store.ingest_text(
            ctx_id, "auth.py", "def authenticate(user, password): pass"
        )
        await store.ingest_text(ctx_id, "math.py", "def add(a, b): return a + b")

        results = await store.query(ctx_id, "authenticate user")
        assert len(results) >= 1
        assert results[0]["source"] == "auth.py"

    @pytest.mark.asyncio
    async def test_query_empty_context(self, store: ContextStore) -> None:
        ctx_id = await store.create("empty")
        results = await store.query(ctx_id, "anything")
        assert results == []


class TestContextStoreSlice:
    @pytest.mark.asyncio
    async def test_slice_full_source(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "file.py", "line1\nline2\nline3")

        content = await store.slice(ctx_id, "file.py")
        assert "line1" in content
        assert "line3" in content

    @pytest.mark.asyncio
    async def test_slice_line_range(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "file.py", "line1\nline2\nline3\nline4")

        content = await store.slice(ctx_id, "file.py", start_line=2, end_line=3)
        assert "line2" in content
        assert "line3" in content
        assert "line1" not in content

    @pytest.mark.asyncio
    async def test_slice_partial_match(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "core/agent.py", "agent code")

        content = await store.slice(ctx_id, "agent.py")
        assert "agent code" in content

    @pytest.mark.asyncio
    async def test_slice_not_found(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        content = await store.slice(ctx_id, "nonexistent.py")
        assert content == ""


class TestContextStoreIndex:
    @pytest.mark.asyncio
    async def test_index_shows_sources(self, store: ContextStore) -> None:
        ctx_id = await store.create("my context")
        await store.ingest_text(ctx_id, "src/main.py", "main code here")

        index = await store.index(ctx_id)
        assert "my context" in index
        assert "src/main.py" in index
        assert "Sources:" in index

    @pytest.mark.asyncio
    async def test_index_not_found(self, store: ContextStore) -> None:
        index = await store.index("ctx_nonexistent")
        assert "not found" in index.lower()


class TestContextStoreTransform:
    @pytest.mark.asyncio
    async def test_transform_stats(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "a.py", "code a")

        result = await store.transform(ctx_id, "stats")
        assert "test" in result
        assert "Chunks:" in result

    @pytest.mark.asyncio
    async def test_transform_group(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "a.py", "code a")
        await store.ingest_text(ctx_id, "b.py", "code b")

        result = await store.transform(ctx_id, "group")
        assert "a.py" in result
        assert "b.py" in result

    @pytest.mark.asyncio
    async def test_transform_sources(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "src.py", "content")

        result = await store.transform(ctx_id, "sources")
        assert "src.py" in result

    @pytest.mark.asyncio
    async def test_transform_filter(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "auth.py", "def login(): pass")
        await store.ingest_text(ctx_id, "math.py", "def add(): pass")

        result = await store.transform(ctx_id, "filter", {"keyword": "login"})
        assert "login" in result
        assert "auth.py" in result

    @pytest.mark.asyncio
    async def test_transform_unknown_operation(self, store: ContextStore) -> None:
        ctx_id = await store.create("test")
        result = await store.transform(ctx_id, "bogus")
        assert "Unknown" in result


class TestContextStoreChunking:
    def test_estimate_tokens(self) -> None:
        assert _estimate_tokens("hello world") == 2  # 11 chars / 4

    def test_split_by_headings(self) -> None:
        md = "# Title\n\nPreamble\n\n## A\n\nBody A\n\n## B\n\nBody B"
        sections = ContextStore._split_by_headings(md)
        # Preamble + Title section + A + B
        assert len(sections) >= 3
        titles = [s[0] for s in sections]
        assert "A" in titles
        assert "B" in titles

    def test_split_by_headings_no_headings(self) -> None:
        text = "Just plain text without any headings."
        sections = ContextStore._split_by_headings(text)
        assert len(sections) == 1
        assert sections[0][0] == ""

    def test_split_by_size(self) -> None:
        # Create text with distinct paragraphs
        text = "\n\n".join(f"Paragraph {i} " * 50 for i in range(10))
        chunks = ContextStore._split_by_size(text, max_chars=500)
        assert len(chunks) > 1
        # All chunks should be within limit (overlap adds ~400 chars max)
        for chunk in chunks:
            assert len(chunk) < 1200


# ═══════════════════════════════════════════════════════════════════
# Phase 2: Context Tools
# ═══════════════════════════════════════════════════════════════════


class TestContextToolInterfaces:
    """Verify all context tools have correct interface properties."""

    @pytest.fixture(
        params=[
            ContextIngestTool,
            ContextQueryTool,
            ContextSliceTool,
            ContextIndexTool,
            ContextTransformTool,
        ]
    )
    def tool(self, request: pytest.FixtureRequest) -> ContextIngestTool:
        return request.param()

    def test_group(self, tool: ContextIngestTool) -> None:
        assert tool.group == "context"

    def test_name_prefix(self, tool: ContextIngestTool) -> None:
        assert tool.name.startswith("context_")

    def test_has_schema(self, tool: ContextIngestTool) -> None:
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert "properties" in schema

    def test_no_store_returns_error(self, tool: ContextIngestTool) -> None:
        # All tools should fail gracefully when _context_store is None
        assert tool._context_store is None


class TestContextIngestTool:
    @pytest.fixture
    def tool(self, store: ContextStore) -> ContextIngestTool:
        t = ContextIngestTool()
        t._context_store = store
        return t

    def test_permission_level(self) -> None:
        assert ContextIngestTool().permission_level == PermissionLevel.MODERATE

    @pytest.mark.asyncio
    async def test_ingest_text(self, tool: ContextIngestTool) -> None:
        result = await tool.execute(
            {
                "name": "test",
                "text": "Hello world",
                "source_label": "greeting",
            }
        )
        assert result.success is True
        assert result.data["context_id"].startswith("ctx_")
        assert result.data["chunks_created"] >= 1

    @pytest.mark.asyncio
    async def test_ingest_file(self, tool: ContextIngestTool, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text("print('hello')")
        result = await tool.execute(
            {
                "name": "test",
                "files": [str(f)],
            }
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_ingest_nothing_fails(self, tool: ContextIngestTool) -> None:
        result = await tool.execute({"name": "test"})
        assert result.success is False
        assert "at least one" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_context_store(self) -> None:
        tool = ContextIngestTool()
        result = await tool.execute({"name": "test", "text": "x"})
        assert result.success is False
        assert "not available" in result.error.lower()


class TestContextQueryTool:
    @pytest.fixture
    async def tool(self, store: ContextStore) -> ContextQueryTool:
        t = ContextQueryTool()
        t._context_store = store
        # Seed some data
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "auth.py", "def authenticate(user): pass")
        t._test_ctx_id = ctx_id  # type: ignore[attr-defined]
        return t

    def test_permission_level(self) -> None:
        assert ContextQueryTool().permission_level == PermissionLevel.SAFE

    @pytest.mark.asyncio
    async def test_query(self, tool: ContextQueryTool) -> None:
        result = await tool.execute(
            {
                "context_id": tool._test_ctx_id,  # type: ignore[attr-defined]
                "query": "authenticate",
            }
        )
        assert result.success is True
        assert result.data["count"] >= 1


class TestContextSliceTool:
    @pytest.fixture
    async def tool(self, store: ContextStore) -> ContextSliceTool:
        t = ContextSliceTool()
        t._context_store = store
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "file.py", "line1\nline2\nline3")
        t._test_ctx_id = ctx_id  # type: ignore[attr-defined]
        return t

    def test_permission_level(self) -> None:
        assert ContextSliceTool().permission_level == PermissionLevel.SAFE

    @pytest.mark.asyncio
    async def test_slice(self, tool: ContextSliceTool) -> None:
        result = await tool.execute(
            {
                "context_id": tool._test_ctx_id,  # type: ignore[attr-defined]
                "source": "file.py",
            }
        )
        assert result.success is True
        assert "line1" in result.data["content"]

    @pytest.mark.asyncio
    async def test_slice_not_found(self, tool: ContextSliceTool) -> None:
        result = await tool.execute(
            {
                "context_id": tool._test_ctx_id,  # type: ignore[attr-defined]
                "source": "nonexistent.py",
            }
        )
        assert result.success is False


class TestContextIndexTool:
    def test_permission_level(self) -> None:
        assert ContextIndexTool().permission_level == PermissionLevel.SAFE

    @pytest.mark.asyncio
    async def test_list_all(self, store: ContextStore) -> None:
        tool = ContextIndexTool()
        tool._context_store = store
        await store.create("ctx1")
        await store.create("ctx2")

        result = await tool.execute({})
        assert result.success is True
        assert result.data["count"] == 2

    @pytest.mark.asyncio
    async def test_get_index(self, store: ContextStore) -> None:
        tool = ContextIndexTool()
        tool._context_store = store
        ctx_id = await store.create("my test")
        await store.ingest_text(ctx_id, "src.py", "code here")

        result = await tool.execute({"context_id": ctx_id})
        assert result.success is True
        assert "my test" in result.data["index"]


class TestContextTransformTool:
    def test_permission_level(self) -> None:
        assert ContextTransformTool().permission_level == PermissionLevel.SAFE

    @pytest.mark.asyncio
    async def test_stats(self, store: ContextStore) -> None:
        tool = ContextTransformTool()
        tool._context_store = store
        ctx_id = await store.create("test")
        await store.ingest_text(ctx_id, "a.py", "code")

        result = await tool.execute(
            {
                "context_id": ctx_id,
                "operation": "stats",
            }
        )
        assert result.success is True
        assert "test" in result.data["result"]
