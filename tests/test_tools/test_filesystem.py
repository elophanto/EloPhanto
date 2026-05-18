"""Tests for file system tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.system.filesystem import FileListTool, FileReadTool, FileWriteTool


class TestFileRead:
    @pytest.fixture
    def read_tool(self) -> FileReadTool:
        return FileReadTool()

    @pytest.mark.asyncio
    async def test_read_existing_file(
        self, read_tool: FileReadTool, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\nline two\n")

        result = await read_tool.execute({"path": str(test_file)})
        assert result.success
        assert "hello world" in result.data["content"]
        assert result.data["line_count"] == 2

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, read_tool: FileReadTool) -> None:
        result = await read_tool.execute({"path": "/nonexistent/file.txt"})
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_line_range(
        self, read_tool: FileReadTool, tmp_path: Path
    ) -> None:
        test_file = tmp_path / "lines.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        result = await read_tool.execute(
            {
                "path": str(test_file),
                "start_line": 2,
                "end_line": 4,
            }
        )
        assert result.success
        content = result.data["content"]
        assert "line2" in content
        assert "line3" in content
        assert "line4" in content
        assert "line1" not in content

    @pytest.mark.asyncio
    async def test_read_directory_fails(
        self, read_tool: FileReadTool, tmp_path: Path
    ) -> None:
        result = await read_tool.execute({"path": str(tmp_path)})
        assert not result.success
        assert "not a file" in result.error.lower()


class TestFileWrite:
    @pytest.fixture
    def write_tool(self) -> FileWriteTool:
        return FileWriteTool()

    @pytest.mark.asyncio
    async def test_write_new_file(
        self, write_tool: FileWriteTool, tmp_path: Path
    ) -> None:
        file_path = tmp_path / "new_file.txt"
        result = await write_tool.execute(
            {
                "path": str(file_path),
                "content": "hello world",
            }
        )
        assert result.success
        assert file_path.exists()
        assert file_path.read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_write_creates_directories(
        self, write_tool: FileWriteTool, tmp_path: Path
    ) -> None:
        file_path = tmp_path / "deep" / "nested" / "dir" / "file.txt"
        result = await write_tool.execute(
            {
                "path": str(file_path),
                "content": "nested content",
            }
        )
        assert result.success
        assert file_path.exists()

    @pytest.mark.asyncio
    async def test_write_creates_backup(
        self, write_tool: FileWriteTool, tmp_path: Path
    ) -> None:
        file_path = tmp_path / "existing.txt"
        file_path.write_text("original content")

        result = await write_tool.execute(
            {
                "path": str(file_path),
                "content": "new content",
                "backup": True,
            }
        )
        assert result.success
        assert result.data["backed_up"] is True
        assert file_path.read_text() == "new content"

        backup_path = file_path.with_suffix(".txt.bak")
        assert backup_path.exists()
        assert backup_path.read_text() == "original content"


class TestFileList:
    @pytest.fixture
    def list_tool(self) -> FileListTool:
        return FileListTool()

    @pytest.mark.asyncio
    async def test_list_directory(
        self, list_tool: FileListTool, tmp_path: Path
    ) -> None:
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.py").write_text("b")
        (tmp_path / "subdir").mkdir()

        result = await list_tool.execute({"path": str(tmp_path)})
        assert result.success
        names = [e["name"] for e in result.data["entries"]]
        assert "file1.txt" in names
        assert "file2.py" in names
        assert "subdir" in names

    @pytest.mark.asyncio
    async def test_list_with_pattern(
        self, list_tool: FileListTool, tmp_path: Path
    ) -> None:
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.py").write_text("b")
        (tmp_path / "file3.txt").write_text("c")

        result = await list_tool.execute(
            {
                "path": str(tmp_path),
                "pattern": "*.py",
            }
        )
        assert result.success
        names = [e["name"] for e in result.data["entries"]]
        assert "file2.py" in names
        assert "file1.txt" not in names

    @pytest.mark.asyncio
    async def test_list_recursive(
        self, list_tool: FileListTool, tmp_path: Path
    ) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("deep")
        (tmp_path / "top.txt").write_text("top")

        result = await list_tool.execute(
            {
                "path": str(tmp_path),
                "recursive": True,
            }
        )
        assert result.success
        names = [e["name"] for e in result.data["entries"]]
        assert "deep.txt" in names
        assert "top.txt" in names

    @pytest.mark.asyncio
    async def test_list_nonexistent_path(self, list_tool: FileListTool) -> None:
        result = await list_tool.execute({"path": "/nonexistent/dir"})
        assert not result.success

    @pytest.mark.asyncio
    async def test_list_excludes_hidden_by_default(
        self, list_tool: FileListTool, tmp_path: Path
    ) -> None:
        (tmp_path / ".hidden").write_text("hidden")
        (tmp_path / "visible.txt").write_text("visible")

        result = await list_tool.execute({"path": str(tmp_path)})
        assert result.success
        names = [e["name"] for e in result.data["entries"]]
        assert "visible.txt" in names
        assert ".hidden" not in names


# ---------------------------------------------------------------------------
# Auto-index hook — file_write hands successful writes to the indexer
# when the target lives inside the configured workspace and is markdown.
# Without this, agent-produced markdown deliverables scatter into
# workspace/ and never become retrievable via knowledge_search.
# ---------------------------------------------------------------------------


class _StubIndexer:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    async def index_file(self, file_path: Path) -> int:
        self.calls.append(file_path)
        return 1


class TestFileWriteAutoIndex:
    @pytest.mark.asyncio
    async def test_indexes_workspace_markdown(self, tmp_path: Path) -> None:
        from tools.system.filesystem import FileWriteTool

        ws = tmp_path / "workspace"
        ws.mkdir()
        target = ws / "deliverable.md"

        tool = FileWriteTool()
        tool._indexer = _StubIndexer()
        tool._workspace_path = ws

        result = await tool.execute(
            {"path": str(target), "content": "# Body", "backup": False}
        )
        assert result.success is True
        assert result.data["indexed"] is True
        assert tool._indexer.calls == [target]

    @pytest.mark.asyncio
    async def test_does_not_index_outside_workspace(self, tmp_path: Path) -> None:
        """A markdown file written outside workspace must not be
        indexed — that path is reserved for operator-curated content
        (knowledge/, skills/) which has its own indexing flow."""
        from tools.system.filesystem import FileWriteTool

        ws = tmp_path / "workspace"
        ws.mkdir()
        outside = tmp_path / "other" / "note.md"

        tool = FileWriteTool()
        tool._indexer = _StubIndexer()
        tool._workspace_path = ws

        result = await tool.execute(
            {"path": str(outside), "content": "# Body", "backup": False}
        )
        assert result.success is True
        assert result.data["indexed"] is False
        assert tool._indexer.calls == []

    @pytest.mark.asyncio
    async def test_does_not_index_non_markdown(self, tmp_path: Path) -> None:
        """JSON/CSV/etc. in workspace shouldn't be indexed — they
        don't chunk well as knowledge and would just create noise."""
        from tools.system.filesystem import FileWriteTool

        ws = tmp_path / "workspace"
        ws.mkdir()
        target = ws / "data.json"

        tool = FileWriteTool()
        tool._indexer = _StubIndexer()
        tool._workspace_path = ws

        result = await tool.execute(
            {"path": str(target), "content": "{}", "backup": False}
        )
        assert result.success is True
        assert result.data["indexed"] is False

    @pytest.mark.asyncio
    async def test_index_failure_does_not_break_write(self, tmp_path: Path) -> None:
        """Indexer is opportunistic. A failing index must not fail
        the write — the file itself landed on disk and the contract
        for file_write is 'wrote the file', not 'and also indexed it'."""
        from tools.system.filesystem import FileWriteTool

        ws = tmp_path / "workspace"
        ws.mkdir()
        target = ws / "doomed.md"

        class _BrokenIndexer:
            async def index_file(self, _p: Path) -> int:
                raise RuntimeError("indexer is on fire")

        tool = FileWriteTool()
        tool._indexer = _BrokenIndexer()
        tool._workspace_path = ws

        result = await tool.execute(
            {"path": str(target), "content": "# Body", "backup": False}
        )
        assert result.success is True
        assert result.data["indexed"] is False
        # The file still exists.
        assert target.exists()

    @pytest.mark.asyncio
    async def test_no_indexer_skips_indexing(self, tmp_path: Path) -> None:
        from tools.system.filesystem import FileWriteTool

        target = tmp_path / "x.md"
        tool = FileWriteTool()
        # indexer left as None — should skip silently.
        result = await tool.execute(
            {"path": str(target), "content": "# Body", "backup": False}
        )
        assert result.success is True
        assert result.data["indexed"] is False
