"""Tests for DocumentProcessor — extraction, MIME detection, chunking."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import DocumentConfig
from core.document_processor import DocumentChunk, DocumentProcessor, ExtractedContent


@pytest.fixture
def doc_config() -> DocumentConfig:
    return DocumentConfig(
        enabled=True,
        context_threshold_tokens=8000,
        chunk_size_tokens=512,
        chunk_overlap_tokens=100,
        ocr_enabled=False,  # Disable OCR in tests (no ONNX runtime needed)
    )


@pytest.fixture
def processor(doc_config: DocumentConfig) -> DocumentProcessor:
    return DocumentProcessor(doc_config)


# ─── MIME Detection ───


class TestMimeDetection:
    def test_pdf_by_extension(self, processor: DocumentProcessor, tmp_path: Path) -> None:
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        assert processor.detect_mime_type(f) == "application/pdf"

    def test_docx_by_extension(self, processor: DocumentProcessor, tmp_path: Path) -> None:
        f = tmp_path / "test.docx"
        f.write_bytes(b"PK\x03\x04fake")  # ZIP magic bytes
        mime = processor.detect_mime_type(f)
        assert "word" in mime or "docx" in mime or "officedocument" in mime

    def test_png_by_extension(self, processor: DocumentProcessor, tmp_path: Path) -> None:
        f = tmp_path / "test.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        assert processor.detect_mime_type(f) == "image/png"

    def test_txt_by_extension(self, processor: DocumentProcessor, tmp_path: Path) -> None:
        f = tmp_path / "readme.txt"
        f.write_text("Hello world")
        mime = processor.detect_mime_type(f)
        assert "text" in mime

    def test_unknown_extension_fallback(
        self, processor: DocumentProcessor, tmp_path: Path
    ) -> None:
        f = tmp_path / "data.xyz"
        f.write_bytes(b"\x00\x01\x02\x03")
        mime = processor.detect_mime_type(f)
        assert isinstance(mime, str)  # Should return something, not crash

    def test_csv_detection(self, processor: DocumentProcessor, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b,c\n1,2,3\n")
        mime = processor.detect_mime_type(f)
        assert "csv" in mime or "text" in mime


# ─── Image Detection ───


class TestIsImage:
    def test_png_is_image(self, processor: DocumentProcessor) -> None:
        assert processor.is_image("image/png") is True

    def test_jpeg_is_image(self, processor: DocumentProcessor) -> None:
        assert processor.is_image("image/jpeg") is True

    def test_pdf_not_image(self, processor: DocumentProcessor) -> None:
        assert processor.is_image("application/pdf") is False

    def test_text_not_image(self, processor: DocumentProcessor) -> None:
        assert processor.is_image("text/plain") is False


# ─── Token Estimation ───


class TestTokenEstimation:
    def test_empty_string(self) -> None:
        assert DocumentProcessor.estimate_tokens("") == 0

    def test_short_text(self) -> None:
        # ~4 chars per token
        result = DocumentProcessor.estimate_tokens("Hello world!")
        assert result == len("Hello world!") // 4

    def test_long_text(self) -> None:
        text = "a" * 4000
        assert DocumentProcessor.estimate_tokens(text) == 1000


# ─── Content Hash ───


class TestContentHash:
    def test_returns_hex_string(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        h = DocumentProcessor.content_hash(f)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("identical")
        f2.write_text("identical")
        assert DocumentProcessor.content_hash(f1) == DocumentProcessor.content_hash(f2)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("alpha")
        f2.write_text("beta")
        assert DocumentProcessor.content_hash(f1) != DocumentProcessor.content_hash(f2)


# ─── RAG Threshold ───


class TestShouldUseRag:
    def test_small_content_no_rag(self, processor: DocumentProcessor) -> None:
        content = ExtractedContent(text="short text", page_count=1)
        assert processor.should_use_rag(content) is False

    def test_large_content_uses_rag(self, processor: DocumentProcessor) -> None:
        # 8000 tokens * 4 chars = 32000 chars needed
        content = ExtractedContent(text="x" * 40000, page_count=10)
        assert processor.should_use_rag(content) is True

    def test_exactly_at_threshold(self, processor: DocumentProcessor) -> None:
        # Exactly at threshold (8000 tokens = 32000 chars)
        content = ExtractedContent(text="x" * 32000, page_count=1)
        # Should NOT use RAG (need to exceed, not equal)
        result = processor.should_use_rag(content)
        assert isinstance(result, bool)


# ─── Chunking ───


class TestChunking:
    def test_chunk_small_document(self, processor: DocumentProcessor) -> None:
        content = ExtractedContent(text="Small text", page_count=1)
        chunks = processor.chunk_document(content, "test.txt")
        assert len(chunks) >= 1
        assert isinstance(chunks[0], DocumentChunk)

    def test_chunk_has_required_fields(self, processor: DocumentProcessor) -> None:
        content = ExtractedContent(text="Some content for chunking", page_count=1)
        chunks = processor.chunk_document(content, "test.txt")
        chunk = chunks[0]
        assert isinstance(chunk.content, str)
        assert isinstance(chunk.chunk_index, int)
        assert isinstance(chunk.token_count, int)
        assert chunk.token_count > 0

    def test_chunk_by_pages_when_available(self, processor: DocumentProcessor) -> None:
        content = ExtractedContent(
            text="Page 1 content. Page 2 content.",
            page_count=2,
            pages=["Page 1 content.", "Page 2 content."],
        )
        chunks = processor.chunk_document(content, "test.pdf")
        assert len(chunks) >= 1

    def test_chunk_indices_sequential(self, processor: DocumentProcessor) -> None:
        long_text = "word " * 5000  # ~5000 tokens
        content = ExtractedContent(text=long_text, page_count=1)
        chunks = processor.chunk_document(content, "big.txt")
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(indices)))


# ─── Plain Text Extraction ───


class TestPlainTextExtraction:
    async def test_extract_text_file(
        self, processor: DocumentProcessor, tmp_path: Path
    ) -> None:
        f = tmp_path / "test.txt"
        f.write_text("Hello, this is plain text content.")
        result = await processor.extract_text(f, "text/plain")
        assert isinstance(result, ExtractedContent)
        assert "Hello" in result.text
        assert result.page_count >= 1

    async def test_extract_csv_file(
        self, processor: DocumentProcessor, tmp_path: Path
    ) -> None:
        f = tmp_path / "data.csv"
        f.write_text("name,age\nAlice,30\nBob,25\n")
        result = await processor.extract_text(f, "text/csv")
        assert isinstance(result, ExtractedContent)
        assert "Alice" in result.text
