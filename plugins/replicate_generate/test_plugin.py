"""Tests for the replicate_generate plugin.

These tests cover:
- Static interface (name, description, schema, permission level)
- _calculate_dimensions math (resolution + aspect ratio)
- execute() validation paths and the URL/local output modes
- _save_local_image with absolute path + knowledge auto-registration
- _resolve_workspace fallback behavior

The plugin talks to the Replicate REST API directly via aiohttp — there is
no `replicate` Python SDK import to mock. _run_replicate_inference is
patched directly when we want to short-circuit the network call.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from plugins.replicate_generate.plugin import ReplicateGenerateTool
from tools.base import PermissionLevel


@pytest.fixture
def tool() -> ReplicateGenerateTool:
    return ReplicateGenerateTool()


# ─────────────────────────────────────────────────────────────────────────────
# Static interface
# ─────────────────────────────────────────────────────────────────────────────


class TestReplicateGenerateToolInterface:
    def test_name(self, tool: ReplicateGenerateTool) -> None:
        assert tool.name == "replicate_generate"

    def test_description_mentions_key_capabilities(
        self, tool: ReplicateGenerateTool
    ) -> None:
        assert "Generates AI images" in tool.description
        assert "Replicate" in tool.description
        # Description should advertise the new behavior so the LLM uses it
        assert "absolute path" in tool.description
        assert "knowledge" in tool.description.lower()

    def test_permission_level(self, tool: ReplicateGenerateTool) -> None:
        assert tool.permission_level == PermissionLevel.MODERATE

    def test_input_schema_structure(self, tool: ReplicateGenerateTool) -> None:
        schema = tool.input_schema
        assert schema["type"] == "object"
        for key in (
            "prompt",
            "resolution",
            "aspect_ratio",
            "output_format",
            "output_mode",
            "filename",
        ):
            assert key in schema["properties"]

    def test_input_schema_requirements_and_defaults(
        self, tool: ReplicateGenerateTool
    ) -> None:
        schema = tool.input_schema
        assert schema["required"] == ["prompt"]
        assert schema["properties"]["resolution"]["default"] == "1024"
        assert schema["properties"]["aspect_ratio"]["default"] == "1:1"
        assert schema["properties"]["output_format"]["default"] == "jpg"
        assert schema["properties"]["output_mode"]["default"] == "url"


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_dimensions
# ─────────────────────────────────────────────────────────────────────────────


class TestReplicateGenerateToolDimensions:
    def test_square(self, tool: ReplicateGenerateTool) -> None:
        assert tool._calculate_dimensions("1024", "1:1") == (1024, 1024)
        assert tool._calculate_dimensions("512", "1:1") == (512, 512)

    def test_landscape_16_9_at_1024(self, tool: ReplicateGenerateTool) -> None:
        # 1024 * 9 / 16 = 576 (already a multiple of 8)
        assert tool._calculate_dimensions("1024", "16:9") == (1024, 576)

    def test_portrait_9_16_at_1024(self, tool: ReplicateGenerateTool) -> None:
        # x=9, y=16 → y > x so height=base, width = 1024*9/16 = 576
        assert tool._calculate_dimensions("1024", "9:16") == (576, 1024)

    def test_landscape_4_3_at_512(self, tool: ReplicateGenerateTool) -> None:
        # x=4, y=3 → width=base=512, height = 512*3/4 = 384 (already /8)
        width, height = tool._calculate_dimensions("512", "4:3")
        assert width == 512
        assert height == 384

    def test_portrait_3_4_at_1024(self, tool: ReplicateGenerateTool) -> None:
        # x=3, y=4 → height=base=1024, width = 1024*3/4 = 768 (multiple of 8)
        width, height = tool._calculate_dimensions("1024", "3:4")
        assert width == 768
        assert height == 1024

    def test_invalid_resolution_raises(self, tool: ReplicateGenerateTool) -> None:
        with pytest.raises(ValueError, match="Invalid resolution"):
            tool._calculate_dimensions("999", "1:1")

    def test_invalid_aspect_ratio_raises(self, tool: ReplicateGenerateTool) -> None:
        with pytest.raises(ValueError, match="Invalid aspect ratio"):
            tool._calculate_dimensions("1024", "21:9")


# ─────────────────────────────────────────────────────────────────────────────
# execute() — validation + happy paths
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestReplicateGenerateToolExecute:
    async def test_missing_prompt_returns_error(
        self, tool: ReplicateGenerateTool
    ) -> None:
        result = await tool.execute({})
        assert result.success is False
        assert "Prompt is required" in (result.error or "")

    async def test_missing_filename_in_local_mode_returns_error(
        self, tool: ReplicateGenerateTool
    ) -> None:
        result = await tool.execute(
            {"prompt": "A cyberpunk city", "output_mode": "local"}
        )
        assert result.success is False
        assert "Filename is required" in (result.error or "")

    async def test_missing_api_key_returns_clear_error(
        self, tool: ReplicateGenerateTool
    ) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(tool, "_load_config", return_value={}):
                result = await tool.execute({"prompt": "test"})
                assert result.success is False
                assert "Replicate API key not found" in (result.error or "")

    async def test_url_mode_returns_just_url(self, tool: ReplicateGenerateTool) -> None:
        async def fake_inference(*args, **kwargs):
            return "https://replicate.delivery/p/abc.jpg"

        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "fake_key"}):
            with patch.object(
                tool, "_run_replicate_inference", side_effect=fake_inference
            ):
                result = await tool.execute(
                    {"prompt": "A cute cat", "resolution": "512", "output_mode": "url"}
                )
                assert result.success is True
                assert result.data["url"] == "https://replicate.delivery/p/abc.jpg"
                # URL mode does NOT include path/absolute_path
                assert "path" not in result.data
                assert "absolute_path" not in result.data

    async def test_inference_failure_surfaces_replicate_error(
        self, tool: ReplicateGenerateTool
    ) -> None:
        async def fake_inference(*args, **kwargs):
            raise Exception("Rate limit exceeded")

        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "fake_key"}):
            with patch.object(
                tool, "_run_replicate_inference", side_effect=fake_inference
            ):
                # output_mode="url" so we don't hit the filename gate
                result = await tool.execute({"prompt": "test", "output_mode": "url"})
                assert result.success is False
                assert "Replicate API error" in (result.error or "")

    async def test_inference_returning_none_is_handled(
        self, tool: ReplicateGenerateTool
    ) -> None:
        async def fake_inference(*args, **kwargs):
            return None

        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "fake_key"}):
            with patch.object(
                tool, "_run_replicate_inference", side_effect=fake_inference
            ):
                result = await tool.execute({"prompt": "test", "output_mode": "url"})
                assert result.success is False
                assert "Failed to retrieve image URL" in (result.error or "")


# ─────────────────────────────────────────────────────────────────────────────
# _save_local_image — A+B+D behavior
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestReplicateGenerateToolSaveLocal:
    """End-to-end behavior of the save path: absolute path under configured
    workspace + auto-registration in knowledge/learned/images/."""

    async def _run_save(
        self,
        tool: ReplicateGenerateTool,
        workspace: Path,
        download_status: int = 200,
        download_body: bytes = b"\xff\xd8\xff\xe0FAKEJPEG",
        raise_oserror: bool = False,
        old_cwd: Path | None = None,
    ) -> Any:
        """Helper to run _save_local_image with mocked HTTP."""
        raw_cfg = {"agent": {"workspace": str(workspace)}}

        class FakeResponse:
            def __init__(self) -> None:
                self.status = download_status

            async def read(self) -> bytes:
                return download_body

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def get(self, *args, **kwargs):
                return FakeResponse()

        cwd = old_cwd or workspace
        prev_cwd = os.getcwd()
        os.chdir(str(cwd))
        try:
            with patch.object(tool, "_load_raw_config", return_value=raw_cfg):
                with patch(
                    "plugins.replicate_generate.plugin.aiohttp.ClientSession",
                    FakeSession,
                ):
                    if raise_oserror:
                        with patch(
                            "plugins.replicate_generate.plugin.aiofiles.open",
                            side_effect=OSError("Disk full"),
                        ):
                            return await tool._save_local_image(
                                "https://example.com/img.jpg",
                                "cat.jpg",
                                prompt="A cute cat",
                                model="google/nano-banana-2",
                                width=512,
                                height=512,
                                output_format="jpg",
                            )
                    else:
                        return await tool._save_local_image(
                            "https://example.com/img.jpg",
                            "cat.jpg",
                            prompt="A cute cat",
                            model="google/nano-banana-2",
                            width=512,
                            height=512,
                            output_format="jpg",
                        )
        finally:
            os.chdir(prev_cwd)

    async def test_success_writes_to_configured_workspace_and_returns_absolute(
        self, tool: ReplicateGenerateTool, tmp_path: Path
    ) -> None:
        result = await self._run_save(tool, tmp_path)
        assert result.success is True
        path = result.data["path"]
        assert os.path.isabs(path)
        assert path == result.data["absolute_path"]
        expected = (tmp_path / "generated_images" / "cat.jpg").resolve()
        assert Path(path).resolve() == expected
        assert Path(path).exists()
        assert Path(path).read_bytes().startswith(b"\xff\xd8\xff\xe0")
        assert result.data["url"] == "https://example.com/img.jpg"
        assert result.data["url_expires_in_hours"] == 12

    async def test_success_auto_registers_in_knowledge_base(
        self, tool: ReplicateGenerateTool, tmp_path: Path
    ) -> None:
        cwd = tmp_path / "agent_root"
        cwd.mkdir()
        result = await self._run_save(tool, tmp_path, old_cwd=cwd)
        assert result.success is True
        kb_dir = cwd / "knowledge" / "learned" / "images"
        kb_files = list(kb_dir.glob("*.md"))
        assert len(kb_files) == 1
        body = kb_files[0].read_text(encoding="utf-8")
        assert "scope: learned" in body
        assert "tags: generated-image, replicate, image, asset" in body
        assert "**Prompt:** A cute cat" in body
        assert "google/nano-banana-2" in body
        assert "512x512 (jpg)" in body
        assert str((tmp_path / "generated_images" / "cat.jpg").resolve()) in body
        assert "browser_upload_file" in body

    async def test_download_404_returns_error_without_writing_file(
        self, tool: ReplicateGenerateTool, tmp_path: Path
    ) -> None:
        result = await self._run_save(tool, tmp_path, download_status=404)
        assert result.success is False
        assert "Download failed with status 404" in (result.error or "")
        assert not (tmp_path / "generated_images" / "cat.jpg").exists()

    async def test_filesystem_oserror_returns_error(
        self, tool: ReplicateGenerateTool, tmp_path: Path
    ) -> None:
        result = await self._run_save(tool, tmp_path, raise_oserror=True)
        assert result.success is False
        assert "File system error" in (result.error or "")

    async def test_knowledge_registration_failure_does_not_break_image_return(
        self, tool: ReplicateGenerateTool, tmp_path: Path
    ) -> None:
        """If knowledge auto-registration fails (e.g. disk full when writing
        the metadata stub), the tool should still return success — the image
        itself was saved."""
        with patch.object(
            tool, "_register_in_knowledge", side_effect=OSError("KB unavailable")
        ):
            result = await self._run_save(tool, tmp_path)
            assert result.success is True
            assert os.path.isabs(result.data["path"])


# ─────────────────────────────────────────────────────────────────────────────
# Workspace resolution
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkspaceResolution:
    def test_uses_configured_agent_workspace(
        self, tool: ReplicateGenerateTool, tmp_path: Path
    ) -> None:
        raw = {"agent": {"workspace": str(tmp_path)}}
        ws = tool._resolve_workspace(raw)
        assert ws == tmp_path.resolve()

    def test_falls_back_to_cwd_workspace_when_unset(
        self, tool: ReplicateGenerateTool, tmp_path: Path
    ) -> None:
        prev = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            ws = tool._resolve_workspace({})
            assert ws == (tmp_path / "workspace").resolve()
        finally:
            os.chdir(prev)

    def test_expands_user_home_in_workspace_path(
        self, tool: ReplicateGenerateTool
    ) -> None:
        raw = {"agent": {"workspace": "~/some-ws"}}
        ws = tool._resolve_workspace(raw)
        assert os.path.isabs(str(ws))
        assert "~" not in str(ws)
