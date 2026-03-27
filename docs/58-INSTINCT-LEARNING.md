# 58 — Instinct-Based Learning

Upgrade to the learning engine: atomic instincts with confidence scoring,
project scoping, quality gates, skill provenance tracking, and pre-tool
guards. Builds on the existing `core/learner.py` lesson extraction.

## Problem

The current `LessonExtractor` auto-saves every lesson to
`knowledge/learned/lessons/` with no quality filtering. Results:
- Lessons accumulate noise (too specific, obvious, or redundant)
- No distinction between project-specific and universal knowledge
- No confidence tracking — every lesson is treated equally
- No evolution path — lessons never become skills or tools
- No provenance — can't tell curated from auto-generated

## Architecture

```
Task completes
      │
      ▼
┌─────────────┐     ┌──────────────┐
│  Instinct   │────►│  Quality     │
│  Extractor  │     │  Gate        │
│  (LLM call) │     │  (overlap    │
│             │     │   check)     │
└─────────────┘     └──────┬───────┘
                           │
                    ┌──────┴───────┐
                    │              │
               ┌────▼────┐  ┌─────▼─────┐
               │ Project │  │  Global   │
               │ Scoped  │  │  Scoped   │
               │ (hash)  │  │           │
               └────┬────┘  └─────┬─────┘
                    │              │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Evolution   │
                    │  Engine      │
                    │  (instinct   │
                    │   → skill)   │
                    └──────────────┘
```

## Layer 1: Instincts (Atomic Learned Behaviors)

An instinct is smaller than a lesson — one trigger, one action, with
confidence scoring.

### Instinct Schema

```python
@dataclass
class Instinct:
    id: str                    # Unique hash
    trigger: str               # When this applies
    action: str                # What to do
    confidence: float          # 0.3 (tentative) to 0.9 (near certain)
    evidence: list[str]        # What observations created it
    scope: str                 # "project" or "global"
    project_hash: str          # Git remote URL hash (project-scoped)
    tags: list[str]            # For search/clustering
    created_at: str
    updated_at: str
    observation_count: int     # How many times observed
```

### Confidence Levels

| Score | Meaning | Promotion Rule |
|-------|---------|---------------|
| 0.3 | Tentative — seen once | Stay project-scoped |
| 0.5 | Likely — seen 2-3 times | Can promote to global |
| 0.7 | Confident — seen across projects | Auto-promote to global |
| 0.9 | Near certain — repeatedly validated | Candidate for skill evolution |

### Storage

```
data/instincts/
  project/<hash>/          # Project-scoped instincts
    instinct_<id>.json
  global/                  # Universal instincts
    instinct_<id>.json
```

### Extraction

After each task, the instinct extractor (replaces the lesson extractor)
runs a lightweight LLM call:

```python
# Extract 0-3 atomic instincts from the completed task
{
  "instincts": [
    {
      "trigger": "when editing React components with state",
      "action": "always check for stale closure references in useEffect",
      "confidence": 0.3,
      "tags": ["react", "hooks", "closures"]
    }
  ]
}
```

The extractor merges with existing instincts:
- Same trigger+action → bump confidence + add evidence
- New → create at 0.3 confidence

## Layer 2: Quality Gate

Before saving, each instinct passes a quality gate:

### Overlap Check
1. Search existing instincts for semantic overlap (fuzzy match on trigger)
2. Search `knowledge/learned/lessons/` for keyword overlap
3. If duplicate found → merge (bump confidence) instead of creating new

### Reusability Check
- Is this specific to one file path? → Drop
- Is this obvious common knowledge? → Drop
- Would this be useful in a different task? → Save

### Scope Decision
- "Would this be useful in a different project?" → Global
- Project-specific pattern (framework, codebase convention) → Project-scoped
- Seen in 2+ projects → Auto-promote to global

## Layer 3: Skill Provenance

Track where every skill and instinct came from:

### Provenance Metadata

Every auto-generated skill/instinct gets a `.provenance.json`:

```json
{
  "source": "instinct-evolution",
  "created_at": "2026-03-27T12:00:00Z",
  "confidence": 0.85,
  "evidence_count": 7,
  "origin_instinct_ids": ["abc123", "def456"],
  "author": "auto-extracted"
}
```

### Skill Tiers

| Tier | Location | Provenance Required |
|------|----------|-------------------|
| Curated | `skills/` | No (shipped with repo) |
| Learned | `data/instincts/` | Yes (auto-tracked) |
| Self-created | `skills/` (via self_create_plugin) | Has plugin metadata |

### Cleanup Rules
- Instincts with confidence < 0.3 after 30 days → auto-delete
- Instincts not referenced in 90 days → flag for review
- Provenance enables safe uninstall/cleanup

## Layer 4: Pre-Tool Guards

Hook into the executor to block or warn before dangerous tool calls:

### Guard Patterns

```python
_PRETOOL_GUARDS = [
    # Warn before git push (review changes first)
    GuardPattern(
        tool="shell_execute",
        pattern=r"\bgit\s+push\b",
        action="warn",
        message="Review changes before pushing.",
    ),
    # Block hardcoded secrets in file writes
    GuardPattern(
        tool="file_write",
        pattern=r"(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36})",
        action="block",
        message="Potential API key/secret detected in file content.",
    ),
]
```

### Integration Point

Guards run in `Executor.execute()` before the tool is called:

```python
# In executor.py, before tool.execute(params):
for guard in _PRETOOL_GUARDS:
    if guard.matches(tool_name, params):
        if guard.action == "block":
            return ToolResult(success=False, error=guard.message)
        elif guard.action == "warn":
            logger.warning("[guard] %s", guard.message)
```

## Layer 5: Instinct Evolution

When instincts cluster around a pattern, they evolve into skills:

### Evolution Triggers
- 5+ instincts with overlapping tags → suggest skill creation
- Single instinct at 0.9 confidence with 10+ observations → standalone skill
- User says "evolve instincts" → review and promote

### Evolution Process
1. Cluster instincts by tag similarity
2. Generate SKILL.md from cluster (LLM call)
3. Save to `skills/<name>/SKILL.md` with provenance
4. Archive source instincts (don't delete — provenance trail)

## Implementation Files

| File | Purpose |
|------|---------|
| `core/instinct.py` | Instinct dataclass, storage, merging, confidence |
| `core/learner.py` | Modified: instinct extraction replaces lesson extraction |
| `core/executor.py` | Modified: pre-tool guards before execution |
| `core/instinct_evolver.py` | Evolution engine (instinct → skill) |
| `data/instincts/` | Storage directory (project + global) |

## Relationship to Existing Systems

| System | Role | Changes |
|--------|------|---------|
| `core/learner.py` | Currently: lesson extraction | Upgrade to instinct extraction |
| `core/memory.py` | Task memory + semantic search | No changes (complementary) |
| `knowledge/learned/` | Lesson KB storage | Kept for backward compat |
| `core/injection_guard.py` | Scans persistence boundaries | Scan instincts too |
| Skills system | SKILL.md files | Instincts evolve into skills |

## Configuration

```yaml
learning:
  enabled: true
  instincts_enabled: true          # New: instinct extraction
  quality_gate: true               # New: overlap + reusability check
  confidence_threshold: 0.3        # Min confidence to keep
  auto_promote_threshold: 0.7      # Auto-promote to global
  evolution_threshold: 0.9         # Candidate for skill evolution
  pretool_guards: true             # New: pre-tool execution guards
  max_instincts_per_project: 200   # Prevent unbounded growth
```
