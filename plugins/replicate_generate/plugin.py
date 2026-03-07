import asyncio
import os
from pathlib import Path
from typing import Any

import aiofiles
import aiohttp
import yaml

from tools.base import BaseTool, PermissionLevel, ToolResult


class ReplicateGenerateTool(BaseTool):
    name: str = "replicate_generate"
    group: str = "media"  # type: ignore[override]
    description: str = (
        "Generates AI images using Replicate API (model configurable in config.yaml) "
        "with support for various resolutions (512px-4K), aspect ratios, "
        "and output formats (URL or local file)."
    )
    permission_level: PermissionLevel = PermissionLevel.MODERATE

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the image to generate.",
                },
                "resolution": {
                    "type": "string",
                    "enum": ["512", "1024", "2048", "4096"],
                    "default": "1024",
                    "description": "Base resolution edge length.",
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["1:1", "16:9", "9:16", "4:3", "3:4"],
                    "default": "1:1",
                    "description": "Aspect ratio of the image.",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["jpg", "png"],
                    "default": "jpg",
                    "description": "Image file format.",
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["url", "local"],
                    "default": "url",
                    "description": "How to return the result. Options: 'url' (returns public URL), 'local' (saves to workspace/generated_images/).",
                },
                "filename": {
                    "type": "string",
                    "description": "Filename for local save. Required if output_mode is 'local'.",
                },
            },
            "required": ["prompt"],
        }

    def _load_config(self) -> dict[str, Any]:
        """Load the replicate section from config.yaml."""
        for config_name in ("config.yaml", "config.yml"):
            config_path = Path(config_name)
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        raw = yaml.safe_load(f) or {}
                    return raw.get("replicate") or {}
                except Exception:
                    pass
        return {}

    def _get_api_key(self, cfg: dict[str, Any]) -> str | None:
        """Read Replicate API key from config, falling back to env var."""
        key = cfg.get("api_key", "")
        if key and not key.startswith("YOUR_"):
            return key
        return os.environ.get("REPLICATE_API_TOKEN") or None

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        try:
            cfg = self._load_config()

            prompt = params.get("prompt")
            resolution = params.get("resolution", cfg.get("default_resolution", "1024"))
            aspect_ratio = params.get(
                "aspect_ratio", cfg.get("default_aspect_ratio", "1:1")
            )
            output_format = params.get(
                "output_format", cfg.get("default_format", "jpg")
            )
            output_mode = params.get(
                "output_mode", cfg.get("default_output_mode", "url")
            )
            model = cfg.get("default_model", "stability-ai/sdxl")
            filename = params.get("filename")

            if not prompt:
                return ToolResult(success=False, error="Prompt is required.")

            if output_mode == "local" and not filename:
                return ToolResult(
                    success=False,
                    error="Filename is required when output_mode is 'local'.",
                )

            # Calculate dimensions
            try:
                width, height = self._calculate_dimensions(resolution, aspect_ratio)
            except ValueError as e:
                return ToolResult(success=False, error=str(e))

            # Validate API Key — read from config.yaml, fall back to env var
            api_token = self._get_api_key(cfg)
            if not api_token:
                return ToolResult(
                    success=False,
                    error="Replicate API key not found. Set it in config.yaml under 'replicate.api_key' or as REPLICATE_API_TOKEN env var.",
                )

            # Run Replicate Generation via HTTP
            try:
                image_url = await self._run_replicate_inference(
                    api_token, model, prompt, width, height, output_format
                )
            except Exception as e:
                return ToolResult(success=False, error=f"Replicate API error: {str(e)}")

            if not image_url:
                return ToolResult(
                    success=False, error="Failed to retrieve image URL from Replicate."
                )

            # Handle Output
            if output_mode == "url":
                return ToolResult(success=True, data={"url": image_url})

            elif output_mode == "local":
                return await self._save_local_image(image_url, filename)

            else:
                return ToolResult(
                    success=False, error=f"Invalid output_mode: {output_mode}"
                )

        except Exception as e:
            return ToolResult(
                success=False, error=f"Unexpected execution error: {str(e)}"
            )

    async def _run_replicate_inference(
        self,
        api_token: str,
        model: str,
        prompt: str,
        width: int,
        height: int,
        output_format: str,
    ) -> str | None:
        """
        Async method to interact with Replicate API directly via HTTP.
        Uses the model specified in config.yaml (default_model).
        """
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }

        input_payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "output_format": output_format,
        }

        # Use the models API for owner/model format, predictions API for version hashes
        if ":" in model:
            create_url = "https://api.replicate.com/v1/predictions"
            body = {"version": model.split(":", 1)[1], "input": input_payload}
        else:
            create_url = f"https://api.replicate.com/v1/models/{model}/predictions"
            body = {"input": input_payload}

        async with aiohttp.ClientSession() as session:
            # Create prediction
            async with session.post(
                create_url,
                headers=headers,
                json=body,
            ) as response:
                if response.status != 201:
                    error_text = await response.text()
                    raise Exception(
                        f"Failed to create prediction: {response.status} - {error_text}"
                    )
                prediction = await response.json()

            # Poll for result
            get_url = f"https://api.replicate.com/v1/predictions/{prediction['id']}"

            while True:
                async with session.get(get_url, headers=headers) as response:
                    prediction = await response.json()

                status = prediction.get("status")
                if status in ["succeeded", "failed", "canceled"]:
                    break

                await asyncio.sleep(1)

            if status != "succeeded":
                error_detail = prediction.get("error", "Unknown error")
                raise Exception(
                    f"Prediction failed with status {status}: {error_detail}"
                )

            output = prediction.get("output")
            if isinstance(output, list) and len(output) > 0:
                return output[0]
            elif isinstance(output, str):
                return output
            else:
                raise Exception("Unexpected output format from Replicate")

    def _calculate_dimensions(
        self, resolution: str, aspect_ratio: str
    ) -> tuple[int, int]:
        """Calculates W/H rounded to nearest multiple of 8."""
        res_map = {
            "512": 512,
            "1024": 1024,
            "2048": 2048,
            "4096": 4096,
        }
        if resolution not in res_map:
            raise ValueError(f"Invalid resolution: {resolution}")

        base_size = res_map[resolution]

        ratio_map = {
            "1:1": (1, 1),
            "16:9": (16, 9),
            "9:16": (9, 16),
            "4:3": (4, 3),
            "3:4": (3, 4),
        }
        if aspect_ratio not in ratio_map:
            raise ValueError(f"Invalid aspect ratio: {aspect_ratio}")

        x, y = ratio_map[aspect_ratio]

        # Determine base dimension based on orientation
        if x >= y:
            width = base_size
            height = int(base_size * (y / x))
        else:
            height = base_size
            width = int(base_size * (x / y))

        # Round to nearest multiple of 8
        def round_to_multiple(n: int, multiple: int = 8) -> int:
            return ((n + multiple // 2) // multiple) * multiple

        width = round_to_multiple(width)
        height = round_to_multiple(height)

        return width, height

    async def _save_local_image(self, url: str, filename: str) -> ToolResult:
        """Downloads and saves the image to the workspace."""
        save_dir = "workspace/generated_images"

        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as e:
            return ToolResult(
                success=False, error=f"Failed to create directory {save_dir}: {str(e)}"
            )

        file_path = os.path.join(save_dir, filename)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return ToolResult(
                            success=False,
                            error=f"Download failed with status {response.status}",
                        )

                    image_bytes = await response.read()

            async with aiofiles.open(file_path, "wb") as f:
                await f.write(image_bytes)

            return ToolResult(success=True, data={"path": file_path, "url": url})

        except aiohttp.ClientError as e:
            return ToolResult(
                success=False, error=f"Network error during download: {str(e)}"
            )
        except OSError as e:
            return ToolResult(success=False, error=f"File system error: {str(e)}")
