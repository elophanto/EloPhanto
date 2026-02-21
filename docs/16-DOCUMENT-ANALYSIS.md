# EloPhanto — Document & Media Analysis

> **Status**: Done

## Overview

EloPhanto can receive files — images, PDFs, Word documents, spreadsheets, code archives — through any channel and analyze them intelligently. Short files go straight into the LLM context. Large documents are chunked, embedded, and stored in a vector collection for retrieval-augmented research across sessions.

This builds on the existing knowledge system (sqlite-vec, Ollama embeddings, hybrid search) and extends it with file-aware parsing, per-document collections, and multi-modal analysis.

---

## Supported File Types

| Category | Formats | Processing |
|----------|---------|------------|
| Images | JPEG, PNG, WebP, GIF, BMP, TIFF, SVG | Vision model analysis (direct) |
| Documents | PDF, DOCX, DOC, ODT, RTF, EPUB | Text extraction → chunking → vector store |
| Spreadsheets | XLSX, XLS, CSV, ODS | Table extraction → structured summary |
| Presentations | PPTX, PPT, ODP | Slide-by-slide extraction (text + images) |
| Code | ZIP, TAR.GZ, single files | Language detection → syntax-aware chunking |
| Plain text | TXT, MD, JSON, XML, YAML, LOG | Direct ingestion, large files chunked |
| Scanned docs | PDF (image-only), photographed pages | OCR → text extraction → chunking |

---

## Architecture

```
Channel (file attachment)
    │
    ▼
File Intake (download, validate, store)
    │
    ▼
Type Router (MIME detection)
    │
    ├── Image ──────────► Vision Model (direct analysis)
    │
    ├── Short Doc ──────► Text Extraction → Context Window (direct)
    │   (< threshold)
    │
    └── Large Doc ──────► Text Extraction → Chunking → Embedding → Vector Store
        (≥ threshold)                                       │
                                                            ▼
                                                    Document Collection
                                                    (query via RAG)
```

### Context Threshold

Documents under a configurable token threshold (default: **8,000 tokens**) are injected directly into the LLM context — no vector store needed. This covers most single-page PDFs, short reports, and typical attachments.

Documents above the threshold go through the full RAG pipeline: chunk, embed, store, retrieve on demand.

---

## File Intake

### Channel Integration

Each channel adapter handles file reception natively and normalizes to a common format before forwarding to the gateway.

**CLI Adapter**:
- User mentions file paths or URLs in their message
- Agent detects paths and uses `document_analyze` tool
- Drag-and-drop file paths from terminal emulators work naturally
- Multiple files in one message: "Compare ~/file1.pdf and ~/file2.pdf"

**Telegram Adapter**:
- Photos and documents arrive as Telegram `File` objects
- Auto-download via Bot API (`bot.download_file()`)
- Supports forwarded documents from other chats
- Photo compression: request original quality via `photo[-1]` (largest size)

**Discord Adapter**:
- Files arrive as `discord.Attachment` objects
- Download via attachment URL
- Supports multiple attachments per message

**Slack Adapter**:
- Files arrive as `files.info` objects
- Download via Slack API with bot token auth
- Supports file threads (multiple files in conversation)

### Gateway Protocol Extension

New message field in the chat message type:

```json
{
  "type": "chat",
  "data": {
    "content": "Analyze this quarterly report",
    "attachments": [
      {
        "filename": "Q4-2025-report.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 2457600,
        "local_path": "/tmp/elophanto/uploads/abc123/Q4-2025-report.pdf",
        "url": null
      }
    ]
  }
}
```

### Storage Layout

EloPhanto needs a structured `data/` directory for all persistent and temporary data. This is a project-wide concern, not just for documents.

```
data/
├── elophanto.db                # SQLite database (already exists)
├── downloads/                  # General-purpose download area
│   └── {session_id}/           # Scoped per session, auto-cleaned
│       └── {uuid}_{filename}
├── documents/                  # Document analysis storage
│   ├── uploads/                # Raw uploaded/downloaded files
│   │   └── {session_id}/
│   │       └── {uuid}_{filename}
│   └── collections/            # Persisted document collections
│       └── {collection_id}/
│           ├── metadata.json   # Source files, creation date, stats
│           └── chunks/         # Extracted text chunks (for re-indexing)
├── cache/                      # Ephemeral cache (embeddings, thumbnails, etc.)
│   ├── embeddings/             # Cached embedding results
│   └── ocr/                    # Cached OCR results by content hash
└── exports/                    # Agent-generated output files
```

**Retention policies**:
- `downloads/` — Cleaned after `download_retention_hours` (default: 24h)
- `documents/uploads/` — Cleaned after `upload_retention_hours` (default: 72h)
- `documents/collections/` — Persist until explicitly deleted by user
- `cache/` — LRU eviction when exceeding `cache_max_mb` (default: 500 MB)
- `exports/` — Persist until explicitly deleted

**Initialization**: The agent creates missing directories on startup. The `data/` directory is gitignored (except `elophanto.db` schema migrations).

**Configuration** (in `config.yaml`):

```yaml
storage:
  data_dir: "data"                    # Base path (relative or absolute)
  download_retention_hours: 24
  upload_retention_hours: 72
  cache_max_mb: 500
  max_file_size_mb: 100               # Reject files larger than this
```

---

## Processing Pipeline

### 1. Text Extraction

| Format | Library | Notes |
|--------|---------|-------|
| PDF (text) | `pymupdf` (PyMuPDF) | Fast, preserves layout, extracts images |
| PDF (scanned) | `pymupdf` + `rapidocr-onnxruntime` | Local OCR, no API calls, good accuracy |
| DOCX | `python-docx` | Full paragraph + table extraction |
| XLSX/CSV | `openpyxl` / `csv` | Sheet-by-sheet, preserve headers |
| PPTX | `python-pptx` | Slide text + speaker notes + embedded images |
| Images (text) | `rapidocr-onnxruntime` | For images containing text (receipts, screenshots) |
| EPUB | `ebooklib` | Chapter-aware extraction |
| Plain text | Built-in | Encoding detection via `charset-normalizer` |

**Why RapidOCR**: Runs locally (ONNX Runtime), no external API, supports 80+ languages, good accuracy on printed text. Fits the local-first philosophy.

### 2. Chunking Strategy

Extends the existing knowledge system chunking (H2 → H3 → paragraph) with document-aware strategies:

**PDF/DOCX — Structural chunking**:
1. Split by document headings/sections if detected
2. Fallback: split by page boundaries (PDFs) or paragraph groups
3. Overlap: 100 tokens between chunks for context continuity
4. Each chunk retains: page number, section title, document title

**Spreadsheets — Row-group chunking**:
1. Headers preserved in every chunk
2. Split by logical row groups (50-100 rows per chunk)
3. Each chunk retains: sheet name, row range, column headers

**Code archives — File-based chunking**:
1. Each file is a chunk (if under 1000 tokens)
2. Large files split by function/class boundaries (tree-sitter)
3. Directory structure preserved as metadata

**Presentations — Slide-based chunking**:
1. Each slide is a chunk (text + speaker notes)
2. Slide images analyzed separately via vision model if needed

### 3. Embedding

Uses the existing Ollama embedding infrastructure:

- **Model**: `nomic-embed-text` (default) or `mxbai-embed-large`
- **Storage**: sqlite-vec in a dedicated `document_chunks` table
- **Metadata columns**: `collection_id`, `source_file`, `page_number`, `section`, `chunk_index`

### 4. Vector Store Schema

```sql
-- Document collections (groups of related files)
CREATE TABLE document_collections (
    collection_id   TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    session_id      TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    file_count      INTEGER DEFAULT 0,
    chunk_count     INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0
);

-- Individual source files within a collection
CREATE TABLE document_files (
    file_id         TEXT PRIMARY KEY,
    collection_id   TEXT REFERENCES document_collections(collection_id),
    filename        TEXT NOT NULL,
    mime_type       TEXT,
    size_bytes      INTEGER,
    page_count      INTEGER,
    local_path      TEXT,
    content_hash    TEXT,
    processed_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Chunks with vector embeddings (extends existing sqlite-vec pattern)
CREATE TABLE document_chunks (
    chunk_id        TEXT PRIMARY KEY,
    collection_id   TEXT REFERENCES document_collections(collection_id),
    file_id         TEXT REFERENCES document_files(file_id),
    chunk_index     INTEGER,
    content         TEXT NOT NULL,
    token_count     INTEGER,
    page_number     INTEGER,
    section_title   TEXT,
    metadata        TEXT,  -- JSON: additional context
    embedding       BLOB   -- sqlite-vec vector
);

CREATE VIRTUAL TABLE document_chunks_vec USING vec0(
    chunk_id TEXT PRIMARY KEY,
    embedding float[768]  -- nomic-embed-text dimension
);
```

---

## Analysis Modes

### Direct Analysis (small files, images)

For files under the context threshold or images:

1. Extract text (or pass image directly to vision model)
2. Inject into LLM context alongside the user's question
3. Single-shot response — no vector store involved

This handles: receipts, screenshots, short memos, single-page contracts, photos.

### RAG Analysis (large documents)

For documents above the context threshold:

1. Parse and chunk the document
2. Embed chunks and store in a collection
3. For each user query, retrieve top-k relevant chunks (default: 10)
4. Inject chunks into context with source attribution (page numbers, sections)
5. LLM generates answer with citations

### Research Mode (multi-document)

For working across multiple documents (research papers, legal documents, financial reports):

1. All documents added to the same collection
2. Cross-document retrieval — queries search across all files simultaneously
3. Citation tracking — responses reference specific documents and pages
4. Follow-up queries build on previous retrievals (conversation-aware RAG)
5. Summary generation — synthesize findings across all documents

```
User: /analyze paper1.pdf paper2.pdf paper3.pdf
Agent: Added 3 files to collection "research-session-abc".
       Total: 847 chunks across 142 pages. Ready for questions.

User: What do all three papers say about attention mechanisms?
Agent: [Response with citations: paper1.pdf p.4, paper2.pdf p.12, paper3.pdf p.7-8]

User: Compare their approaches to multi-head attention
Agent: [Cross-document comparison with specific page references]
```

### Image Analysis

Images are analyzed using vision-capable models:

1. **Local VLMs** (preferred): LLaVA, Qwen2-VL, or similar via Ollama
2. **Cloud fallback**: Claude (via OpenRouter/direct), GPT-4o
3. **Combined**: For scanned documents — OCR extracts text, vision model interprets layout/diagrams

The LLM router selects the best available vision model based on the existing routing priority.

---

## Tools

### `document_analyze`

Primary tool for file analysis. Handles routing to the correct pipeline.

```yaml
name: document_analyze
description: Analyze documents, images, PDFs, and other files
parameters:
  files:
    type: array
    description: File paths or URLs to analyze
  question:
    type: string
    description: What to analyze or extract (optional — defaults to general summary)
  collection_name:
    type: string
    description: Name for the document collection (optional — auto-generated)
  mode:
    type: string
    enum: [auto, direct, rag, research]
    description: Analysis mode (auto selects based on file size)
```

### `document_query`

Query an existing document collection.

```yaml
name: document_query
description: Ask questions about previously analyzed documents
parameters:
  collection:
    type: string
    description: Collection name or ID
  question:
    type: string
    description: The question to answer from the documents
  top_k:
    type: integer
    description: Number of chunks to retrieve (default 10)
```

### `document_collections`

List and manage document collections.

```yaml
name: document_collections
description: List, inspect, or delete document collections
parameters:
  action:
    type: string
    enum: [list, info, delete]
  collection:
    type: string
    description: Collection name or ID (required for info/delete)
```

---

## How It Works in Chat

There are no special commands. Files are handled naturally through conversation:

**Telegram/Discord/Slack**: Send a file with a message. The channel adapter detects the attachment, downloads it, and the agent analyzes it as part of the conversation.

**CLI**: Mention a file path or URL in your message. The agent detects it and uses `document_analyze` as a tool.

```
User: What does this say? [attaches receipt.jpg via Telegram]
User: Summarize ~/Documents/report.pdf
User: Compare these two contracts [attaches contract-a.pdf and contract-b.pdf]
User: What are the key metrics in https://example.com/quarterly-report.pdf
```

The agent decides the right analysis mode (direct vs RAG) automatically based on file size. No user intervention needed.

For managing collections, the agent uses `document_collections` as a tool when asked:

```
User: What documents do I have loaded?
User: Delete the research collection
```

---

## Configuration

```yaml
documents:
  enabled: true

  # Context threshold: docs below this go direct, above go through RAG
  context_threshold_tokens: 8000

  # RAG settings
  chunk_size_tokens: 512
  chunk_overlap_tokens: 100
  retrieval_top_k: 10

  # Embedding model (uses existing knowledge system config as default)
  embedding_model: "nomic-embed-text"

  # Vision model for images (uses LLM router if not specified)
  vision_model: null

  # OCR
  ocr_enabled: true
  ocr_languages: ["en"]

  # Storage
  upload_dir: "data/uploads"
  upload_retention_hours: 72
  max_file_size_mb: 100
  max_collection_files: 50

  # Supported MIME types (extend as needed)
  allowed_types:
    - "application/pdf"
    - "application/vnd.openxmlformats-officedocument.*"
    - "application/vnd.ms-*"
    - "image/*"
    - "text/*"
    - "application/zip"
    - "application/epub+zip"
```

---

## Dependencies

New packages required:

| Package | Purpose | Size |
|---------|---------|------|
| `pymupdf` | PDF text + image extraction | ~15 MB |
| `rapidocr-onnxruntime` | Local OCR engine | ~30 MB (with models) |
| `python-docx` | DOCX parsing | ~1 MB |
| `openpyxl` | XLSX parsing | ~4 MB |
| `python-pptx` | PPTX parsing | ~2 MB |
| `ebooklib` | EPUB parsing | ~0.5 MB |
| `charset-normalizer` | Encoding detection | ~0.3 MB |

All run locally — no external API calls for parsing or OCR. Vision model analysis uses the existing LLM router.

**Optional**:
| Package | Purpose | Size |
|---------|---------|------|
| `tree-sitter` + language grammars | Code-aware chunking | ~5 MB per language |
| `camelot-py` | Table extraction from PDFs | ~10 MB |

---

## Integration with Existing Systems

### Knowledge System

Document collections are a parallel store to the existing `knowledge/` markdown base. They share:

- Same sqlite-vec infrastructure
- Same embedding models via Ollama
- Same hybrid search (semantic + keyword)

The difference: knowledge files are long-lived markdown the agent maintains. Document collections are user-uploaded files stored in their original parsed form.

A future bridge: the agent can extract key findings from documents and write them as knowledge files for permanent retention.

### Session System

Document collections can be scoped to sessions (temporary research) or global (persistent reference library). Session-scoped collections are cleaned up with the session. Global collections persist across sessions and channels.

### Permission System

File analysis respects the existing permission tiers:

- `ask_always`: Confirm before processing each file
- `smart_auto`: Auto-approve for read-only analysis, ask for collection creation
- `full_auto`: Everything auto-approved

---

## Example Flows

### Casual: "What's in this receipt?"

```
[User sends a photo of a restaurant receipt via Telegram]
User: How much was this?

→ Image detected (JPEG, 245 KB)
→ Route to vision model (direct analysis)
→ Vision model reads receipt text and layout

Agent: The receipt is from Osteria Roma, dated Feb 18, 2026.
       Total: €47.50 (2x pasta €14, 1x wine €12, 1x dessert €7.50).
```

### Practical: "Summarize this contract"

```
User: Summarize ~/Documents/lease-agreement.pdf

→ PDF detected (18 pages, 12,400 tokens)
→ Above threshold → RAG pipeline
→ Extract text (pymupdf), chunk (28 chunks), embed, store

Agent: Created collection "lease-agreement" (18 pages, 28 chunks).

       Summary: 12-month residential lease starting March 1, 2026.
       Monthly rent: $2,400. Security deposit: $4,800. Key clauses:
       - 60-day notice for termination (§4.2)
       - No subletting without written consent (§7.1)
       - Landlord responsible for structural repairs (§9.3)

       Ask me anything about the contract.

User: What happens if I break the lease early?

→ Retrieve chunks matching "early termination" / "break lease"
→ Top chunks: §4.2 (p.5), §4.5 (p.6), §12.1 (p.15)

Agent: Per §4.2, early termination requires 60-day written notice
       and a fee of 2 months' rent ($4,800). Exception in §4.5:
       if relocating >100 miles for employment, the fee is waived
       with proof of employment change. See pages 5-6.
```

### Research: "Compare these papers"

```
[User sends paper1.pdf, paper2.pdf, paper3.pdf via Telegram]
User: These are papers on transformer architectures. I'm writing a literature review.

→ 3 PDFs detected (combined: 87 pages, ~52,000 tokens)
→ All above threshold → RAG pipeline, single collection
→ Collection "transformer-research" created (312 chunks)

Agent: Added 3 papers to collection "transformer-research":
       1. "Attention Is All You Need" (Vaswani et al.) — 15 pages
       2. "BERT: Pre-training of Deep Bidirectional Transformers" — 16 pages
       3. "GPT-4 Technical Report" — 56 pages
       Ready for research queries.

User: How does each paper handle positional encoding?

→ Cross-document retrieval for "positional encoding"
→ Chunks from all 3 papers retrieved with page citations

Agent: [Detailed comparison with citations from each paper]
```
