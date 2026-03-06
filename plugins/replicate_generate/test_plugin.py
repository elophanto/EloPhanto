import os
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from plugins.replicate_generate.plugin import ReplicateGenerateTool
from tools.base import PermissionLevel, ToolResult


@pytest.fixture
def tool():
    return ReplicateGenerateTool()


class TestReplicateGenerateToolInterface:
    """Tests for the tool's static interface properties."""

    def test_name(self, tool):
        assert tool.name == "replicate_generate"

    def test_description(self, tool):
        assert "Generates AI images" in tool.description
        assert "Replicate" in tool.description

    def test_permission_level(self, tool):
        assert tool.permission_level == PermissionLevel.MODERATE

    def test_input_schema_structure(self, tool):
        schema = tool.input_schema
        assert schema["type"] == "object"

        props = schema["properties"]
        assert "prompt" in props
        assert "resolution" in props
        assert "aspect_ratio" in props
        assert "output_format" in props
        assert "output_mode" in props
        assert "filename" in props

    def test_input_schema_requirements(self, tool):
        schema = tool.input_schema
        assert schema["required"] == ["prompt"]

        # Check defaults
        assert schema["properties"]["resolution"]["default"] == "1024"
        assert schema["properties"]["aspect_ratio"]["default"] == "1:1"
        assert schema["properties"]["output_format"]["default"] == "jpg"
        assert schema["properties"]["output_mode"]["default"] == "url"


class TestReplicateGenerateToolHelpers:
    """Tests for internal helper methods."""

    def test_calculate_dimensions_square(self, tool):
        assert tool._calculate_dimensions("1024", "1:1") == (1024, 1024)
        assert tool._calculate_dimensions("512", "1:1") == (512, 512)

    def test_calculate_dimensions_landscape(self, tool):
        # 16:9 -> 1024 base width
        # Height = 1024 * 9 / 16 = 576. Divisible by 8.
        assert tool._calculate_dimensions("1024", "16:9") == (1024, 576)

    def test_calculate_dimensions_portrait(self, tool):
        # 9:16 -> 1024 base height
        # Width = 1024 * 9 / 16 = 576.
        assert tool._calculate_dimensions("1024", "9:16") == (576, 1024)

    def test_calculate_dimensions_rounding(self, tool):
        # 4:3 on 512 base -> 512 * 4 / 3 = 682.66.
        # Rounded to nearest multiple of 8 -> 680.
        width, height = tool._calculate_dimensions("512", "4:3")
        assert width == 512
        assert height == 680

    def test_calculate_dimensions_invalid_resolution(self, tool):
        with pytest.raises(ValueError, match="Invalid resolution"):
            tool._calculate_dimensions("999", "1:1")

    def test_calculate_dimensions_invalid_aspect_ratio(self, tool):
        with pytest.raises(ValueError, match="Invalid aspect ratio"):
            tool._calculate_dimensions("1024", "21:9")


@pytest.mark.asyncio
class TestReplicateGenerateToolExecute:
    """Tests for the main execute method."""

    async def test_execute_missing_prompt(self, tool):
        result = await tool.execute({})
        assert result.success is False
        assert "Prompt is required" in result.error

    async def test_execute_missing_filename_local_mode(self, tool):
        result = await tool.execute(
            {"prompt": "A cyberpunk city", "output_mode": "local"}
        )
        assert result.success is False
        assert "Filename is required" in result.error

    async def test_execute_missing_api_key(self, tool):
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "plugins.replicate_generate.plugin.Path.exists", return_value=False
            ):
                result = await tool.execute({"prompt": "test"})
                assert result.success is False
                assert "Replicate API key not found" in result.error

    async def test_execute_replicate_api_error(self, tool):
        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "fake_key"}):
            mock_client = MagicMock()
            mock_client.run.side_effect = Exception("Rate limit exceeded")

            with patch(
                "plugins.replicate_generate.plugin.replicate.Client",
                return_value=mock_client,
            ):
                result = await tool.execute({"prompt": "test"})
                assert result.success is False
                assert "Replicate API error" in result.error

    async def test_execute_success_url_mode(self, tool):
        mock_url = "https://replicate.delivery/p/abc123.jpg"

        mock_client = MagicMock()
        # Simulate returning a list of strings (common Replicate output)
        mock_client.run.return_value = [mock_url]

        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "fake_key"}):
            with patch(
                "plugins.replicate_generate.plugin.replicate.Client",
                return_value=mock_client,
            ):
                result = await tool.execute(
                    {"prompt": "A cute cat", "resolution": "512"}
                )

                assert result.success is True
                assert result.data["url"] == mock_url

    async def test_execute_success_local_mode(self, tool):
        mock_url = "https://replicate.delivery/p/abc123.jpg"
        mock_client = MagicMock()
        mock_client.run.return_value = [mock_url]

        # Mock the internal save method to avoid actual filesystem operations
        tool._save_local_image = AsyncMock(
            return_value=ToolResult(
                success=True,
                data={"path": "workspace/generated_images/cat.jpg", "url": mock_url},
            )
        )

        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "fake_key"}):
            with patch(
                "plugins.replicate_generate.plugin.replicate.Client",
                return_value=mock_client,
            ):
                result = await tool.execute(
                    {
                        "prompt": "A cute cat",
                        "output_mode": "local",
                        "filename": "cat.jpg",
                    }
                )

                assert result.success is True
                assert result.data["path"] == "workspace/generated_images/cat.jpg"
                # Ensure the save method was called with the correct URL
                tool._save_local_image.assert_awaited_once_with(mock_url, "cat.jpg")

    async def test_execute_empty_output_from_replicate(self, tool):
        mock_client = MagicMock()
        mock_client.run.return_value = []  # Empty list

        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "fake_key"}):
            with patch(
                "plugins.replicate_generate.plugin.replicate.Client",
                return_value=mock_client,
            ):
                result = await tool.execute({"prompt": "test"})

                assert result.success is False
                assert "Failed to retrieve image URL" in result.error


@pytest.mark.asyncio
class TestReplicateGenerateToolSaveLocal:
    """Tests for the local image saving logic."""

    async def test_save_local_image_success(self, tool):
        mock_url = "http://example.com/img.jpg"
        filename = "test.jpg"
        expected_path = "workspace/generated_images/test.jpg"

        # Mock aiohttp and aiofiles
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"fake_image_bytes")

        mock_session = AsyncMock()
        mock_session.get.return_value.__aenter__.return_value = mock_response

        # We must patch aiofiles.open as a context manager
        mock_file = AsyncMock()
        mock_file.write = AsyncMock()

        with patch("aiohttp.ClientSession") as MockSession:
            MockSession.return_value.__aenter__.return_value = mock_session

            with patch("aiofiles.open", create=True) as MockOpen:
                MockOpen.return_value.__aenter__.return_value = mock_file

                result = await tool._save_local_image(mock_url, filename)

                assert result.success is True
                assert result.data["path"] == expected_path
                assert result.data["url"] == mock_url

    async def test_save_local_image_download_error(self, tool):
        mock_response = AsyncMock()
        mock_response.status = 404

        mock_session = AsyncMock()
        mock_session.get.return_value.__aenter__.return_value = mock_response

        with patch("aiohttp.ClientSession") as MockSession:
            MockSession.return_value.__aenter__.return_value = mock_session

            result = await tool._save_local_image("http://bad.url", "fail.jpg")

            assert result.success is False
            assert "Download failed with status 404" in result.error

    async def test_save_local_image_filesystem_error(self, tool):
        # Mock successful download but fail during write
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"bytes")

        mock_session = AsyncMock()
        mock_session.get.return_value.__aenter__.return_value = mock_response

        with patch("aiohttp.ClientSession") as MockSession:
            MockSession.return_value.__aenter__.return_value = mock_session

            with patch("aiofiles.open", side_effect=OSError("Disk full")):
                result = await tool._save_local_image("http://good.url", "fail.jpg")

                assert result.success is False
                assert "File system error" in result.error
