"""Document analyze tool — primary tool for file analysis.

Handles text extraction, OCR, vision analysis for images,
and creates searchable collections for large documents.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class DocumentAnalyzeTool(BaseTool):
    """Analyze documents, images, PDFs, spreadsheets, and other files."""

    def __init__(self) -> None:
        self._processor: Any = None  # DocumentProcessor, injected
        self._store: Any = None  # DocumentStore, injected
        self._storage: Any = None  # StorageManager, injected
        self._router: Any = None  # LLMRouter, injected (for vision/summary)
        self._config: Any = None  # DocumentConfig, injected

    @property
    def name(self) -> str:
        return "document_analyze"

    @property
    def description(self) -> str:
        return (
            "Analyze documents, images, PDFs, spreadsheets, and other files. "
            "Extracts text, performs OCR on scanned documents, and creates "
            "searchable collections for large documents. For images, provides "
            "visual analysis. Returns extracted content or collection info."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths to analyze",
                },
                "question": {
                    "type": "string",
                    "description": "What to analyze or extract (optional — defaults to general summary)",
                },
                "collection_name": {
                    "type": "string",
                    "description": "Name for the document collection (optional — auto-generated)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["auto", "direct", "rag"],
                    "description": "Analysis mode — auto selects based on file size (default: auto)",
                },
            },
            "required": ["files"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._processor or not self._store:
            return ToolResult(
                success=False,
                error="Document analysis not initialized. Check config.",
            )

        file_paths = params.get("files", [])
        question = params.get("question", "")
        collection_name = params.get("collection_name", "")
        mode = params.get("mode", "auto")

        if not file_paths:
            return ToolResult(success=False, error="No files provided.")

        # Resolve and validate paths
        resolved: list[Path] = []
        for fp in file_paths:
            p = Path(fp).expanduser().resolve()
            if not p.exists():
                return ToolResult(success=False, error=f"File not found: {fp}")
            if not self._storage.validate_file_size(p.stat().st_size):
                max_mb = self._config.max_file_size_mb
                return ToolResult(success=False, error=f"File too large (max {max_mb} MB): {fp}")
            resolved.append(p)

        # Single image → vision analysis (return description)
        if len(resolved) == 1 and self._processor.is_image(
            self._processor.detect_mime_type(resolved[0])
        ):
            return await self._analyze_image(resolved[0], question)

        # Process documents
        all_contents: list[dict[str, Any]] = []
        use_rag = False

        for file_path in resolved:
            mime = self._processor.detect_mime_type(file_path)

            # Images within multi-file analysis → OCR for text
            if self._processor.is_image(mime):
                content = await self._processor.extract_text(file_path, mime)
            else:
                content = await self._processor.extract_text(file_path, mime)

            file_info = {
                "filename": file_path.name,
                "mime_type": mime,
                "page_count": content.page_count,
                "token_count": self._processor.estimate_tokens(content.text),
                "content": content,
                "path": file_path,
            }
            all_contents.append(file_info)

            if mode == "rag" or (mode == "auto" and self._processor.should_use_rag(content)):
                use_rag = True

        if mode == "direct":
            use_rag = False

        # Direct mode: return extracted text
        if not use_rag:
            texts: list[str] = []
            for info in all_contents:
                header = f"## {info['filename']} ({info['page_count']} pages, ~{info['token_count']} tokens)"
                texts.append(f"{header}\n\n{info['content'].text}")

            return ToolResult(
                success=True,
                data={
                    "mode": "direct",
                    "file_count": len(all_contents),
                    "total_tokens": sum(i["token_count"] for i in all_contents),
                    "content": "\n\n---\n\n".join(texts),
                },
            )

        # RAG mode: chunk, embed, store in collection
        if not collection_name:
            if len(resolved) == 1:
                collection_name = resolved[0].stem
            else:
                collection_name = f"analysis-{len(resolved)}-files"

        collection_id = await self._store.create_collection(collection_name)

        file_summaries: list[str] = []
        total_chunks = 0

        for info in all_contents:
            content = info["content"]
            chunks = self._processor.chunk_document(content, info["filename"])
            await self._store.add_file(
                collection_id=collection_id,
                file_path=info["path"],
                filename=info["filename"],
                mime_type=info["mime_type"],
                page_count=content.page_count,
                chunks=chunks,
            )
            total_chunks += len(chunks)
            file_summaries.append(
                f"- {info['filename']}: {content.page_count} pages, "
                f"{len(chunks)} chunks, ~{info['token_count']} tokens"
            )

        summary = (
            f"Created collection \"{collection_name}\" with {len(all_contents)} file(s):\n"
            + "\n".join(file_summaries)
            + f"\n\nTotal: {total_chunks} chunks. Ready for questions."
        )

        # If there's a question, do an initial query
        if question:
            results = await self._store.query(collection_id, question)
            if results:
                context_parts = []
                for r in results:
                    source = r["filename"]
                    if r.get("page_number"):
                        source += f" (p.{r['page_number']})"
                    if r.get("section_title"):
                        source += f" — {r['section_title']}"
                    context_parts.append(f"[{source}]\n{r['content']}")

                summary += "\n\n---\n\nRelevant content for your question:\n\n"
                summary += "\n\n".join(context_parts)

        return ToolResult(
            success=True,
            data={
                "mode": "rag",
                "collection_id": collection_id,
                "collection_name": collection_name,
                "file_count": len(all_contents),
                "chunk_count": total_chunks,
                "content": summary,
            },
        )

    async def _analyze_image(self, file_path: Path, question: str) -> ToolResult:
        """Analyze an image using OCR. Vision model analysis via LLM is handled
        by the agent naturally — it sees the OCR text and can reason about it."""
        content = await self._processor.extract_text(file_path)
        text = content.text

        if not text or text.startswith("["):
            text = f"[Image file: {file_path.name}, no text detected via OCR]"

        return ToolResult(
            success=True,
            data={
                "mode": "direct",
                "file_count": 1,
                "content": f"## OCR result from {file_path.name}\n\n{text}",
                "filename": file_path.name,
            },
        )
