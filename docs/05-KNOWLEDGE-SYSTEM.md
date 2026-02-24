# EloPhanto — Knowledge System

## Philosophy

All knowledge in EloPhanto is stored as markdown. Markdown is chosen because:

- It is human-readable and human-editable — both the user and the agent can work with it
- It is structured enough for programmatic parsing (headings, lists, code blocks, frontmatter)
- LLMs understand markdown natively and produce high-quality markdown output
- It requires no special tooling — any text editor works
- It is version-controllable with git
- It is the same format used by Claude's knowledge system, providing familiar patterns

## Directory Structure

```
knowledge/
├── system/                          # Agent's self-documentation
│   ├── architecture.md              # How EloPhanto is built
│   ├── capabilities.md              # Current list of all tools and plugins
│   ├── conventions.md               # Coding standards, patterns, project rules
│   ├── changelog.md                 # History of all changes (self-development log)
│   ├── identity.md                  # Who EloPhanto is, its purpose, its principles
│   ├── known-limitations.md         # What it knows it can't do (yet)
│   ├── designs/                     # Design documents for self-developed features
│   └── decisions/                   # Architecture Decision Records (ADRs)
│
├── user/                            # User-provided knowledge
│   ├── (any structure the user wants)
│   └── ...
│
├── learned/                         # Agent-discovered knowledge
│   ├── tasks/                       # Summaries of completed tasks
│   ├── patterns/                    # Patterns the agent has identified
│   ├── failures/                    # Documented failures and lessons learned
│   └── services/                    # Discovered info about external services
│
└── plugins/                         # Plugin documentation (mirrored from /plugins/*/README.md)
    ├── gmail_reader.md
    ├── slack_notifier.md
    └── ...
```

## File Format

Every knowledge file should follow this structure:

```markdown
---
title: [Descriptive title]
created: [ISO datetime]
updated: [ISO datetime]
tags: [comma-separated tags for search]
scope: [system | user | learned | plugin]
---

# Title

Content goes here. Use standard markdown with headings, 
lists, code blocks, tables, and links.

## Sections

Organize content with clear heading hierarchy.
H2 for major sections, H3 for subsections.

## Related

- Links to related knowledge files
- [[relative/path/to/file.md]]
```

The YAML frontmatter is optional but recommended. The agent should always include it in files it creates. It helps with indexing and search.

## Indexing and Retrieval

### Chunking Strategy

Markdown files are split into chunks for embedding. The chunking strategy respects document structure:

1. **Primary split**: By H2 headings. Each H2 section becomes a chunk.
2. **Overflow handling**: If a section exceeds 1000 tokens, split further by H3 headings.
3. **Still too large**: Split by paragraphs, keeping at least 200 tokens per chunk.
4. **Minimum chunk**: Sections under 50 tokens are merged with the next section.

Each chunk retains metadata: source file path, heading hierarchy (breadcrumb), frontmatter tags, and position in the document.

### Embedding

Chunks are embedded via the configured provider. The default is `auto`, which selects the fastest available:

1. **OpenRouter** (cloud, default if API key configured) — `google/gemini-embedding-001`, fast, cheap, high-quality multilingual embeddings
2. **Ollama** (local fallback) — `nomic-embed-text` (primary) or `mxbai-embed-large` (fallback), free but requires local GPU

The provider is configured in `config.yaml`:

```yaml
knowledge:
  embedding_provider: auto  # auto | openrouter | ollama
  embedding_openrouter_model: google/gemini-embedding-001
  embedding_model: nomic-embed-text       # Ollama model
  embedding_fallback: mxbai-embed-large   # Ollama fallback
```

When `auto` is set (default), the agent uses OpenRouter if an API key is configured, otherwise falls back to Ollama. Switching providers triggers automatic reindexing since embedding dimensions may differ.

Embeddings are stored in SQLite using the `sqlite-vec` extension, alongside the chunk text and metadata.

### Search

The `knowledge_search` tool performs hybrid search:

1. **Semantic search**: Query is embedded, cosine similarity against stored vectors. Top 20 candidates.
2. **Keyword boost**: Exact keyword matches in the chunk text or metadata tags get a score boost.
3. **Recency boost**: More recently updated documents get a slight score boost (configurable).
4. **Scope filtering**: Results can be filtered by knowledge scope (system, user, learned, plugins).
5. **Final ranking**: Combine semantic similarity + keyword boost + recency, return top N results.

### Indexing Triggers

Re-indexing happens:

- On agent startup (incremental — only files changed since last index; auto-recovers with full re-index if chunks exist but embeddings are missing)
- When `knowledge_write` creates or modifies a file
- When `knowledge_index` is explicitly called
- On a configurable schedule (default: every 6 hours while agent is running)

Indexing is non-blocking — the agent can continue working while re-indexing happens in the background.

## Agent Self-Knowledge

The `/knowledge/system/` directory is special. It is how EloPhanto understands itself. The agent reads these files on every startup and uses them to contextualize its actions.

### `identity.md`

Who EloPhanto is. Ships with a default that the agent can evolve:

```markdown
---
title: EloPhanto Identity
updated: [date]
---

# Who I Am

I am EloPhanto, a self-evolving AI agent. I run locally on my user's machine
and help them accomplish tasks by using my tools, knowledge, and the ability
to create new capabilities when needed.

# My Principles

- I am transparent about what I can and cannot do
- I ask for permission when my actions have consequences
- I document everything I build and learn
- I test my own code rigorously before deploying it
- I protect my user's security and privacy
- I grow more capable over time, but never at the cost of reliability
```

### `capabilities.md`

A living document listing everything EloPhanto can currently do. Updated automatically by the self-development pipeline. The agent consults this during planning to know what tools are available.

### `conventions.md`

Coding standards and patterns. The agent reads this before every development task. Includes:

- File naming conventions
- Code style preferences
- Error handling patterns
- Testing requirements
- Documentation standards
- Import ordering
- How to structure a plugin

This file can be edited by both the user (to impose preferences) and the agent (to add learned patterns).

### `changelog.md`

Reverse-chronological log of all changes. Auto-generated by the self-development pipeline:

```markdown
## 2026-02-17 — Added Gmail Reader Plugin

- **Type**: New plugin
- **Reason**: User requested email summarization
- **Details**: Created `gmail_reader` plugin using Google Gmail API. 
  Supports reading, searching, and listing emails.
- **Tests**: 12 passed, 0 failed
- **Dependencies**: google-api-python-client, google-auth-oauthlib
```

## User Knowledge

The `/knowledge/user/` directory is entirely user-managed. Users can:

- Drop any markdown files here and they will be indexed
- Organize with any subdirectory structure they prefer
- Include project documentation, personal notes, reference materials, SOPs
- Edit the files at any time — changes are picked up on next index cycle

The agent treats user knowledge as authoritative — if user knowledge conflicts with learned knowledge, user knowledge takes precedence.

## Learned Knowledge

The `/knowledge/learned/` directory is where EloPhanto stores things it discovers on its own:

### `tasks/`

After completing a task, the agent writes a summary:

```markdown
---
title: Summarized Gmail inbox
created: 2026-02-17T10:30:00Z
tags: gmail, email, summarization
---

# Task: Summarize unread Gmail messages

## What was asked
User requested a summary of unread emails.

## What I did
1. Built gmail_reader plugin (first time — see changelog)
2. Retrieved 23 unread messages
3. Summarized using Claude Sonnet via OpenRouter

## Outcome
Successfully delivered summary. User was satisfied.

## Notes
- Gmail API rate limits: 250 quota units per user per second
- OAuth token stored in vault as `gmail_oauth_token`
```

### `patterns/`

When the agent notices recurring patterns across tasks, it documents them:

```markdown
---
title: User prefers bullet-point summaries
created: 2026-02-18T09:00:00Z
tags: user-preference, formatting
---

# Pattern: Summary Format Preference

Across 5 summarization tasks, the user has consistently 
asked for bullet points when I initially provided prose.
Default to bullet-point format for summaries going forward.
```

### `failures/`

When something goes wrong, the agent documents the failure and the lesson:

```markdown
---
title: Failed to create Slack integration
created: 2026-02-19T14:00:00Z
tags: slack, failure, oauth
---

# Failure: Slack Integration

## What happened
Attempted to create a Slack plugin. OAuth flow failed because 
Slack requires a redirect URI that must be HTTPS, but the local 
development server uses HTTP.

## Root cause
Slack's OAuth2 implementation requires HTTPS redirect URIs 
even for local development (unlike Google's APIs).

## Lesson learned
Need to either:
1. Set up a local HTTPS tunnel (e.g., ngrok)
2. Use Slack's socket mode instead of OAuth for local agents

## Attempts
3 attempts, all failed at the same OAuth stage. Stopped per 
retry policy. Awaiting user guidance.
```
