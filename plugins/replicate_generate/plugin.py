import asyncio
import os
import re
from datetime import UTC, datetime
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
        "and output formats (URL or local file). Local saves go to "
        "<workspace>/generated_images/ and return an absolute path; the prompt "
        "and metadata are auto-registered in knowledge/learned/images/ for later "
        "retrieval via knowledge_search."
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
        raw = self._load_raw_config()
        return raw.get("replicate") or {}

    def _load_raw_config(self) -> dict[str, Any]:
        """Load the full config.yaml as a dict (or {} if not found)."""
        for config_name in ("config.yaml", "config.yml"):
            config_path = Path(config_name)
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        return yaml.safe_load(f) or {}
                except Exception:
                    pass
        return {}

    def _resolve_workspace(self, raw: dict[str, Any]) -> Path:
        """Resolve the agent's configured workspace as an absolute Path.

        Falls back to ``<project_root>/workspace`` when ``agent.workspace``
        is unset or empty. Always returns an absolute path so generated
        artifacts have a single, predictable home regardless of CWD.
        """
        ws = (raw.get("agent") or {}).get("workspace") or ""
        if ws:
            return Path(ws).expanduser().resolve()
        # Fall back to project_root/workspace (CWD is project root at runtime)
        return (Path.cwd() / "workspace").resolve()

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
                # filename is guaranteed non-None here (validated above when
                # output_mode == "local"), but assert for mypy.
                assert filename is not None
                return await self._save_local_image(
                    image_url,
                    filename,
                    prompt=prompt,
                    model=model,
                    width=width,
                    height=height,
                    output_format=output_format,
                )

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

    async def _save_local_image(
        self,
        url: str,
        filename: str,
        prompt: str,
        model: str,
        width: int,
        height: int,
        output_format: str,
    ) -> ToolResult:
        """Downloads and saves the image under the configured workspace.

        Returns an absolute path so any downstream tool (browser_upload_file,
        file_read, etc.) can use it without worrying about CWD. After a
        successful save, also writes a metadata stub to
        ``knowledge/learned/images/`` so the agent can find this image later
        via ``knowledge_search`` (e.g. "the meeting avatar I made yesterday").
        """
        raw_cfg = self._load_raw_config()
        workspace = self._resolve_workspace(raw_cfg)
        save_dir = workspace / "generated_images"

        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return ToolResult(
                success=False, error=f"Failed to create directory {save_dir}: {str(e)}"
            )

        file_path = (save_dir / filename).resolve()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return ToolResult(
                            success=False,
                            error=f"Download failed with status {response.status}",
                        )

                    image_bytes = await response.read()

            async with aiofiles.open(str(file_path), "wb") as f:
                await f.write(image_bytes)

            absolute_path = str(file_path)

            # Auto-register in knowledge base (best-effort, never blocks)
            try:
                self._register_in_knowledge(
                    absolute_path=absolute_path,
                    url=url,
                    prompt=prompt,
                    model=model,
                    width=width,
                    height=height,
                    output_format=output_format,
                )
            except Exception:
                # Silently ignore — knowledge registration is a nice-to-have.
                pass

            return ToolResult(
                success=True,
                data={
                    "path": absolute_path,
                    "absolute_path": absolute_path,
                    "url": url,
                    "url_expires_in_hours": 12,
                },
            )

        except aiohttp.ClientError as e:
            return ToolResult(
                success=False, error=f"Network error during download: {str(e)}"
            )
        except OSError as e:
            return ToolResult(success=False, error=f"File system error: {str(e)}")

    def _register_in_knowledge(
        self,
        absolute_path: str,
        url: str,
        prompt: str,
        model: str,
        width: int,
        height: int,
        output_format: str,
    ) -> None:
        """Write a markdown metadata file for the generated image.

        Stored under ``knowledge/learned/images/`` so the existing knowledge
        indexer picks it up. Filename is ``{date}-{slug}.md`` where slug is
        derived from the first few words of the prompt (sanitized).
        """
        # Build a safe filename slug from the prompt (~50 chars max)
        slug_source = (prompt or "image").lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug_source).strip("-")
        slug = (slug[:50].rstrip("-")) or "image"

        now = datetime.now(UTC)
        date_str = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        md_filename = f"{date_str}-{slug}-{timestamp[-6:]}.md"

        # Same project root the plugin saw at startup
        kb_dir = Path.cwd() / "knowledge" / "learned" / "images"
        kb_dir.mkdir(parents=True, exist_ok=True)
        md_path = kb_dir / md_filename

        # Front matter + body — matches the existing learned-knowledge format
        frontmatter = (
            "---\n"
            f"created: '{date_str}'\n"
            f"updated: '{date_str}'\n"
            "scope: learned\n"
            "tags: generated-image, replicate, image, asset\n"
            f"title: 'Generated image: {prompt[:60].replace(chr(39), chr(8217))}'\n"
            "---\n\n"
        )
        body = (
            "# Generated Image\n\n"
            f"**Prompt:** {prompt}\n\n"
            f"- **Model:** `{model}`\n"
            f"- **Size:** {width}x{height} ({output_format})\n"
            f"- **Saved at:** `{absolute_path}`\n"
            f"- **Replicate URL:** {url}\n"
            f"  *(URL expires after ~12 hours — use the local path for "
            "anything beyond that.)*\n"
            f"- **Generated:** {now.isoformat()}\n\n"
            "## Reuse hint\n\n"
            "When the user asks for an image matching this prompt, prefer the "
            "saved local path above over re-generating. To upload to a website "
            "via the browser, pass the **absolute path** to "
            "`browser_upload_file` or `browser_file_chooser`.\n"
        )

        md_path.write_text(frontmatter + body, encoding="utf-8")
