# EloPhanto — Self-Learning Model Pipeline

> **Status: Dataset Builder Done** — The agent-side data collection pipeline is fully implemented. Training pipeline remains in idea phase.

## Overview

EloPhanto currently relies on external LLM providers (Z.ai, OpenRouter) and local generic models (Ollama). The next step is training a **custom EloPhanto base model** — fine-tuned specifically for agent tasks: tool selection, multi-step planning, code generation, and self-reflection.

The model is trained on EloPhanto's own interaction data, published to HuggingFace, deployed locally via Ollama, and continuously improved as new data accumulates. Each training cycle produces a better model that understands EloPhanto's tool system, permission model, and task patterns.

### What's Implemented

The **dataset builder** — the agent-side collection pipeline — is fully operational:

- `core/dataset_builder.py` — `DataSanitizer`, `QualityFilter`, `DatasetBuilder` classes
- 14 regex patterns strip secrets locally before data ever leaves the machine (defense in depth)
- PII removal (paths, emails), browser data exclusion, large content truncation
- Quality filtering with configurable thresholds (min turns, success/failure collection)
- Signal extraction: user sentiment (positive/negative/neutral), denial detection, error detection
- Local SQLite buffer with batch upload to the collection API
- Auto-registration via census fingerprint, key recovery on 409 conflict
- Fire-and-forget pattern — all collection code is exception-safe, never blocks the agent

### What's Not Implemented Yet

- Training pipeline (Unsloth + HF Jobs)
- Model publishing to HuggingFace
- Ollama deployment and auto-pull
- Benchmark suite

### Why a Custom Model

- **Task-specific performance** — A model fine-tuned on actual agent interactions outperforms generic models at tool selection, parameter formatting, and multi-step planning
- **Cost reduction** — Replace expensive cloud API calls with a local model for routine tasks
- **Privacy** — All inference runs locally, no data leaves the machine
- **Self-improvement** — The agent literally gets smarter over time from its own experience
- **Offline capability** — Works without internet after initial model download

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      EloPhanto Self-Learning Loop                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌─────────┐  ┌───────┐  │
│   │ Collect  │──►│ Collect  │──►│  Store   │──►│  Train  │─►│Publish│  │
│   │  Data    │   │   API    │   │ Dataset  │   │ HF Jobs │  │  HF   │  │
│   └────▲─────┘   └──────────┘   └─────────┘   └─────────┘  └───┬───┘  │
│        │         elophanto.com   HF Datasets                    │      │
│        │                                                        │      │
│        │          ┌─────────┐    ┌─────────┐                    │      │
│        └──────────│  Deploy │◄───│  Pull   │◄───────────────────┘      │
│                   │  Ollama │    │  Model  │                           │
│                   └─────────┘    └─────────┘                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

```
Detailed Flow:

Agent Interactions ──► Local Sanitizer ──► elophanto.com/api/collect
                                           (validate, dedup, batch)
                                                     │
                                            (periodic push)
                                                     │
                                                     ▼
                                            HuggingFace Dataset Repo
                                            (EloPhanto/dataset)
                                                     │
                                            (size threshold met)
                                                     │
                                                     ▼
                                            HF Jobs + Unsloth
                                            (QLoRA on managed GPU)
                                                     │
                                                     ▼
                                            HuggingFace Model Repo
                                            (EloPhanto/base-model)
                                                     │
                                           ┌─────────┴──────────┐
                                           ▼                    ▼
                                    safetensors/LoRA       GGUF export
                                    (for HF inference)  (for Ollama deploy)
                                                            │
                                                            ▼
                                                    Ollama Model Pull
                                                    (elophanto:latest)
                                                            │
                                                            ▼
                                                    Agent uses new model
                                                    (better performance)
                                                            │
                                                            ▼
                                                    More interactions ──► Loop
```

## Dataset System

### Automated Collection

The agent captures training data from its own interactions:

| Data Type | Source | Example |
|-----------|--------|---------|
| Planning traces | `core/planner.py` | Goal → plan steps → tool sequence |
| Tool calls | `core/executor.py` | Tool name, parameters, result, success/failure |
| Conversations | `core/session.py` | User message → agent response pairs |
| Reflections | `core/reflector.py` | What worked, what failed, lessons learned |
| Code generation | `tools/self_dev/` | Task description → generated code → test results |

### Collection Pipeline

Data flows from individual agents to the central dataset via a collection API on **elophanto.com**:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Agent Instance  │     │  Agent Instance  │     │  Agent Instance  │
│  (user machine)  │     │  (user machine)  │     │  (user machine)  │
└────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
         │                        │                        │
         │  1. Local sanitization │                        │
         │  2. Quality filtering  │                        │
         │  3. Opt-in consent     │                        │
         │                        │                        │
         ▼                        ▼                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                  elophanto.com/api/collect                        │
│                                                                  │
│  • Validate & verify sanitization (reject if secrets detected)   │
│  • Deduplicate across all agents (embedding similarity)          │
│  • Batch into staging buffer                                     │
│  • Monitor dataset size threshold                                │
│  • Rate limit per agent (prevent abuse)                          │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                    (batch threshold met)
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│               HuggingFace Datasets (EloPhanto/dataset)           │
│                                                                  │
│  • Versioned JSONL files pushed periodically                     │
│  • Dataset card auto-updated with stats                          │
│  • Triggers training when retrain_threshold reached              │
└──────────────────────────────────────────────────────────────────┘
```

**Agent-side flow** (runs locally, implemented in `core/dataset_builder.py`):

1. After each task (successful or failed), the agent passes the interaction to `DatasetBuilder.record_task()`
2. `QualityFilter` checks minimum turn count (default 2) — single-message interactions are skipped
3. `DataSanitizer` strips credentials (14 regex patterns), PII (paths, emails), vault references, browser tool calls/results, and truncates large tool outputs
4. `_extract_signals()` analyzes raw messages for training-relevant signals: user sentiment, denial detection, error detection, turn count
5. Sanitized conversations + enriched metadata are buffered in local SQLite (`collect_examples` table)
6. When the buffer reaches `batch_size` (default 10), `DatasetBuilder` uploads to `POST /v1/collect` with Bearer auth
7. Auto-registration: on first upload, the agent registers via `/v1/auth/register` using its census fingerprint, stores the API key in `data/.collect_key`
8. On 409 (already registered but key file lost), tries `/v1/auth/recover` to retrieve the existing key
9. On 401 (key invalid), clears cached key and re-registers next time
10. On agent shutdown, `flush()` uploads any remaining buffered examples

**Server-side flow** (elophanto.com):

1. Receives sanitized examples via `POST /api/collect`
2. Runs a second-pass validation (regex secret scan, length checks, format validation)
3. Rejects any example that fails validation — agent is notified
4. Deduplicates against existing dataset (embedding similarity > 0.95)
5. Stores accepted examples in a staging buffer
6. Periodically (e.g. daily) pushes new batches to the HuggingFace dataset repo
7. When the dataset crosses the retrain threshold, triggers a training job via `hf jobs`

**API contract**:

```
POST /api/collect
Authorization: Bearer <agent_api_key>
Content-Type: application/json

{
  "agent_version": "0.1.0",
  "examples": [
    {
      "id": "task-uuid",
      "conversations": [...],
      "metadata": {...}
    }
  ]
}

Response: 200 OK
{
  "accepted": 3,
  "rejected": 1,
  "reasons": ["secret_detected_in_example_2"],
  "dataset_size": 4523,
  "next_training_at": 5000
}
```

Agents authenticate with a per-installation API key (stored in vault as `elophanto_collect_key`). This is separate from the HuggingFace token — users don't need HF accounts to contribute data.

### Data Format

Each training example is a conversation in the standard chat format:

```json
{
  "id": "task-uuid",
  "conversations": [
    {
      "role": "system",
      "content": "You are EloPhanto, a self-evolving AI agent with access to tools..."
    },
    {
      "role": "user",
      "content": "List all Python files in the project and count lines of code"
    },
    {
      "role": "assistant",
      "content": "I'll use shell_execute to find Python files and count lines.\n\n<tool_call>\n{\"name\": \"shell_execute\", \"params\": {\"command\": \"find . -name '*.py' | xargs wc -l\"}}\n</tool_call>"
    },
    {
      "role": "tool",
      "content": "{\"stdout\": \"...\", \"exit_code\": 0}"
    },
    {
      "role": "assistant",
      "content": "Here are the results: ..."
    }
  ],
  "metadata": {
    "task_type": "planning",
    "tools_used": ["shell_execute"],
    "success": true,
    "duration_seconds": 4.2,
    "model_used": "glm-4.7",
    "timestamp": "2026-02-18T10:30:00Z",
    "turn_count": 5,
    "has_tool_use": true,
    "has_denials": false,
    "has_errors": false,
    "user_sentiment": "positive"
  }
}
```

### Central Dataset Repository

The dataset lives on HuggingFace Datasets for direct integration with the training pipeline (HF Jobs loads it natively via `load_dataset()`):

```
Repository: huggingface.co/datasets/EloPhanto/dataset

elophanto-dataset/
├── README.md                    # Dataset card
├── data/
│   ├── v1/
│   │   ├── planning.jsonl       # Planning traces
│   │   ├── tool_use.jsonl       # Tool call examples
│   │   ├── conversations.jsonl  # Full conversations
│   │   ├── code_gen.jsonl       # Code generation examples
│   │   └── reflections.jsonl    # Self-reflection data
│   └── v2/
│       └── ...                  # Next collection cycle
├── stats.json                   # Dataset statistics
└── scripts/
    ├── validate.py              # Data validation
    ├── deduplicate.py           # Remove duplicates
    └── merge.py                 # Merge dataset versions
```

### Quality Filtering

Not all interactions produce good training data. The agent-side `QualityFilter` applies configurable criteria before buffering:

| Filter | Default | Purpose |
|--------|---------|---------|
| **Min turns** | 2 | Exclude trivial single-message interactions |
| **Success only** | `false` | Collect both successes and failures — failures are negative examples for DPO/RLHF |
| **Tool use required** | `false` | Pure text conversations (user feedback, corrections) are collected for sentiment data |

The server side applies additional filters:

| Filter | Purpose |
|--------|---------|
| **Secret scan** | Reject examples with detected credentials (14 regex patterns) |
| **Deduplication** | Remove near-identical conversations (embedding similarity > 0.95 via pgvector) |
| **Length bounds** | Reject extremely short or excessively long examples |

### Signal Extraction

Each collected example is enriched with training-relevant signals (extracted by `_extract_signals()` in `core/dataset_builder.py`):

| Signal | Source | Use in Training |
|--------|--------|-----------------|
| `user_sentiment` | User messages ("thanks", "wrong", "doesn't work") | Weight positive examples higher, use negative for alignment |
| `has_denials` | Tool outputs ("permission denied", "unauthorized") | Teach the model to handle permission failures |
| `has_errors` | Tool/assistant messages ("error", "traceback", "failed") | Negative examples for error recovery training |
| `turn_count` | User + assistant message count | Complexity indicator for curriculum learning |
| `has_tool_use` | Whether any tools were called | Distinguish tool-use vs. pure-text examples |

### Privacy & Security

Training data is sanitized **locally on the agent** before being sent to the collection API (defense in depth — the server re-scans too):

| Layer | What | How |
|-------|------|-----|
| **Credentials** | API keys, tokens, passwords, private keys | 14 regex patterns matching GitHub PATs, OpenAI keys, AWS keys, HF tokens, Slack tokens, Bearer JWTs, EloPhanto keys, and more |
| **Vault references** | `vault:xxx` patterns | Replaced with `[VAULT_REF]` |
| **PII — paths** | `/Users/username/...`, `/home/username/...` | Replaced with `/REDACTED_PATH` |
| **PII — emails** | Email addresses | Replaced with `[EMAIL]` |
| **File contents** | Large tool outputs (>2000 chars) | Truncated with `[...truncated]` |
| **Browser data** | All `browser_*` tool calls and their responses | Entirely dropped from the conversation |
| **Configurable opt-out** | Users can disable collection entirely | `self_learning.enabled: false` (default) |

The same 14 secret patterns are implemented on both sides (`core/dataset_builder.py` and `elophanto.com/lib/collect.ts`) so secrets are caught even if one layer misses them.

## Training Pipeline

### Base Model Selection

Start with a strong open-source instruct model suitable for agent tasks. Unsloth recommends starting with instruct models as they allow direct fine-tuning using conversational chat templates and require less data than base models.

| Candidate | Size | Why |
|-----------|------|-----|
| **Qwen3-4B-Instruct** | 4B | Best fine-tuning results at small scale — matches 120B+ teacher after tuning, runs on consumer GPU. Top pick for starting small. |
| **Qwen3-Coder-30B-A3B** | 30B (3B active) | State-of-the-art agentic coding model, MoE architecture, strong on tool use and browser-use tasks. Available on Ollama. |
| **GLM-4.7-Flash** | 30B (3B active) | MoE, 200K context, strong at coding/tool use/agentic tasks. Already in EloPhanto's ecosystem via Z.ai. Available on Ollama. |
| **Qwen3** | 8B / 14B | Dense models, strong reasoning + tool use, 2x faster with Unsloth. Good middle ground. |
| **DeepSeek-V3.2** | varies | Frontier reasoning + agentic workloads, strong tool-use. |
| **SmolLM3** | 3B | Apache 2, 128K context (YaRN), detailed training configs for easy fine-tuning. Lightweight option. |
| **Gemma 3** | 4B / 12B | Good at structured output, well-suited for classification and specialized fine-tuning. |

**Recommended starting point**: **Qwen3-4B-Instruct** — small enough for cheap HF Jobs training (~$0.60/hr on T4), proven fine-tuning results, and deployable on any consumer hardware via Ollama. Scale up to Qwen3-Coder-30B-A3B or GLM-4.7-Flash once the pipeline is validated and dataset is larger.

MoE models (Qwen3-Coder, GLM-4.7-Flash) only activate ~3B parameters per token despite having 30B total, making them efficient for both training and local inference. Unsloth supports all models that work in transformers.

### Unsloth Fine-Tuning

[Unsloth](https://github.com/unslothai/unsloth) provides 2x faster fine-tuning with 70% less VRAM via optimized kernels. Supports QLoRA, GRPO (reinforcement learning), vision models, and MoE architectures (12x faster MoE training).

The training script runs as a [HuggingFace Job](https://huggingface.co/blog/unsloth-jobs) — a UV script with inline dependencies submitted via the `hf` CLI:

```python
# /// script
# dependencies = ["unsloth", "trl>=0.12.0", "datasets", "trackio"]
# ///

from unsloth import FastLanguageModel
from trl import SFTTrainer, SFTConfig
from datasets import load_dataset

# Load base model with QLoRA (4-bit)
model, tokenizer = FastLanguageModel.from_pretrained(
    "unsloth/Qwen3-4B-Instruct",
    load_in_4bit=True,
    max_seq_length=8192,
)

# Apply LoRA adapters
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    lora_alpha=32,
    lora_dropout=0,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
)

# Load EloPhanto interaction dataset from HuggingFace
dataset = load_dataset("EloPhanto/dataset", split="train")

# Train
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    args=SFTConfig(
        output_dir="./output",
        push_to_hub=True,
        hub_model_id="EloPhanto/base-model",
        per_device_train_batch_size=4,
        gradient_accumulation_steps=4,
        num_train_epochs=3,
        learning_rate=2e-4,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        bf16=True,
        packing=True,
        report_to="trackio",
    ),
)

trainer.train()

# Push safetensors + LoRA adapters to HuggingFace Hub
trainer.push_to_hub()

# Export GGUF for Ollama deployment
model.save_pretrained_gguf(
    "output-gguf",
    tokenizer,
    quantization_method="q4_k_m",
    push_to_hub=True,
    hub_model_id="EloPhanto/base-model-gguf",
)
```

### Training Triggers

Retraining is triggered when conditions are met:

| Trigger | Threshold |
|---------|-----------|
| **Dataset size** | New data exceeds 5,000 examples since last training |
| **Time-based** | At least 2 weeks since last training run |
| **Manual** | Triggered centrally by maintainer |
| **Quality signal** | Agent task success rate drops below threshold |

### Training Infrastructure

Training runs on **[HuggingFace Jobs](https://huggingface.co/docs/hub/jobs)** with **[Unsloth](https://github.com/unslothai/unsloth)** — fully managed cloud GPUs, no infrastructure to provision. This provides:

- **Consistent environment** — Managed GPU instances with reproducible dependencies
- **Native HF integration** — Reads datasets via `load_dataset()`, pushes models via `push_to_hub()`
- **Real-time monitoring** — Loss curves and metrics via [Trackio](https://huggingface.co/docs/trackio)
- **Cost-effective** — ~$1-4 per training run for 1-8B models (A10G GPUs)
- **No user burden** — Users contribute data, not compute

| Model Size | Recommended GPU | Cost/Hour |
|------------|-----------------|-----------|
| < 1B params | `t4-small` | ~$0.40 |
| 1-3B params | `t4-medium` | ~$0.60 |
| 3-7B params | `a10g-small` | ~$1.00 |
| 7-13B params | `a10g-large` | ~$3.00 |

Training is triggered via the `hf` CLI when dataset thresholds are met. Users receive the trained model via HuggingFace/Ollama — they never need to run training themselves.

```bash
# Submit a training job
hf jobs uv run scripts/train.py \
    --flavor a10g-small \
    --secrets HF_TOKEN \
    --timeout 4h \
    --dataset EloPhanto/dataset \
    --output-repo EloPhanto/base-model \
    --num-epochs 3 \
    --eval-split 0.1
```

## Model Registry

### HuggingFace Repository

Two repos are published per training run:

**Weights + LoRA adapters**: **https://huggingface.co/EloPhanto/base-model**

```
EloPhanto/base-model/
├── README.md              # Model card (auto-generated)
├── config.json            # Model configuration
├── tokenizer.json         # Tokenizer
├── model.safetensors      # Model weights (or adapter weights)
├── adapter_config.json    # LoRA adapter config
└── training_metadata.json # Training details
```

**GGUF for Ollama**: **https://huggingface.co/EloPhanto/base-model-gguf**

```
EloPhanto/base-model-gguf/
├── README.md                          # Model card
├── elophanto-base-q4_k_m.gguf        # Quantized GGUF (primary)
└── elophanto-base-q8_0.gguf          # Higher quality GGUF (optional)
```

The GGUF export is handled in the training script itself via `model.save_pretrained_gguf()`, so both repos are updated atomically by the same HF Job.

### Versioning Scheme

```
v0.1.0  — First fine-tune on initial dataset (~1K examples)
v0.2.0  — Second cycle with 5K+ examples
v0.3.0  — Third cycle, expanded tool coverage
v1.0.0  — Production-ready, benchmarked against cloud models
```

Each version includes:
- Training dataset version and size
- Base model used
- Benchmark scores (tool accuracy, planning quality, code generation)
- Comparison with previous version

### Model Card

Auto-generated model card includes:

- Base model and fine-tuning method
- Dataset description (size, categories, collection period)
- Benchmark results
- Intended use (EloPhanto agent, tool-use, planning)
- Limitations and known weaknesses
- Training hyperparameters

## Deployment

### Ollama Integration

The trained model is converted to GGUF format and served via Ollama:

```bash
# Create Modelfile
FROM ./elophanto-base-v0.2.0.gguf

PARAMETER temperature 0.7
PARAMETER num_ctx 8192

SYSTEM "You are EloPhanto, a self-evolving AI agent..."

# Import into Ollama
ollama create elophanto:v0.2.0 -f Modelfile
ollama create elophanto:latest -f Modelfile
```

### Auto-Pull New Versions

When a new model version is published:

1. Agent detects new version available (periodic check or notification)
2. Downloads GGUF from HuggingFace
3. Creates new Ollama model tag
4. Updates `config.yaml` routing to use new version
5. Keeps previous version as fallback

### Fallback Strategy

```
Primary:    elophanto:latest (custom fine-tuned model)
Fallback 1: elophanto:v{previous} (previous version)
Fallback 2: qwen3-coder:30b-a3b (base model via Ollama, MoE, best agentic coding)
Fallback 3: Z.ai / OpenRouter (cloud API)
```

If the new model shows regression (lower task success rate over N tasks), automatically roll back to the previous version and flag for investigation.

## Continuous Improvement Loop

### The Cycle

```
 ┌─────────────────────────────────────────────────┐
 │                                                 │
 │   1. COLLECT                                    │
 │   Agent runs tasks, interactions are captured   │
 │                    │                            │
 │                    ▼                            │
 │   2. FILTER & UPLOAD                             │
 │   Local sanitization + quality filtering         │
 │   POST to elophanto.com/api/collect              │
 │                    │                            │
 │                    ▼                            │
 │   3. EVALUATE TRIGGER                           │
 │   Enough new data? Time threshold met?          │
 │                    │                            │
 │                    ▼                            │
 │   4. TRAIN                                      │
 │   HF Jobs + Unsloth QLoRA on managed GPU        │
 │                    │                            │
 │                    ▼                            │
 │   5. BENCHMARK                                  │
 │   Evaluate on held-out test set                 │
 │   Compare with previous model version           │
 │                    │                            │
 │                    ▼                            │
 │   6. PUBLISH                                    │
 │   Upload to HuggingFace with version tag        │
 │                    │                            │
 │                    ▼                            │
 │   7. DEPLOY                                     │
 │   Pull into Ollama, update routing config       │
 │                    │                            │
 │                    ▼                            │
 │   8. MONITOR                                    │
 │   Track task success rate with new model         │
 │   Auto-rollback if regression detected          │
 │                    │                            │
 │                    └──────────► Back to 1.      │
 │                                                 │
 └─────────────────────────────────────────────────┘
```

### Evaluation Benchmarks

| Metric | Description | Target |
|--------|-------------|--------|
| **Tool accuracy** | Correct tool selected for the task | > 90% |
| **Parameter accuracy** | Correct parameters passed to tools | > 85% |
| **Plan quality** | Multi-step plans complete tasks successfully | > 80% |
| **Code generation** | Generated code passes tests on first try | > 70% |
| **Reflection quality** | Useful self-corrections when errors occur | > 75% |
| **Response coherence** | Clear, well-structured responses | > 90% |

Benchmarks are evaluated on a held-out test set (10% of dataset, never seen during training).

### Version Comparison

Each new model version is compared against:

1. The previous EloPhanto model version
2. The base model (untuned)
3. A cloud model (Z.ai GLM-4.7) as reference ceiling

A new version is only deployed if it matches or exceeds the previous version on all core metrics.

## Configuration

```yaml
# config.yaml
self_learning:
  enabled: false                    # Opt-in (disabled by default)
  collect_endpoint: "https://api.elophanto.com/v1/collect"
  register_endpoint: "https://api.elophanto.com/v1/auth/register"
  batch_size: 10                    # Upload every N buffered examples
  min_turns: 2                      # Minimum user+assistant turns to collect
  success_only: false               # Collect failures too (negative examples)
  privacy:
    strip_credentials: true         # 14 regex patterns for API keys, tokens, etc.
    strip_pii: true                 # Paths (/Users/xxx), emails
    strip_file_contents: true       # Truncate large tool outputs to 2000 chars
    exclude_browser_data: true      # Drop browser_* tool calls and results
```

API key management is automatic — the agent registers with the collection API on first upload using its census fingerprint (`sha256:xxx`), stores the key in `data/.collect_key`, and recovers via `/v1/auth/recover` if the key file is lost. No user configuration needed beyond setting `enabled: true`.

### Future: Training Configuration (Not Yet Implemented)

```yaml
# config.yaml (future additions)
self_learning:
  # ... existing fields above ...
  dataset_repo: "EloPhanto/dataset"
  model_repo: "EloPhanto/base-model"
  gguf_repo: "EloPhanto/base-model-gguf"
  hf_token_ref: hf_token
  training:
    gpu_flavor: a10g-small
    timeout_hours: 4
    base_model: "unsloth/Qwen3-4B-Instruct"
  auto_retrain: false
  retrain_threshold: 5000
```

## Implementation Status

### Done: Dataset Builder

The agent-side data collection pipeline is fully implemented and tested:

| Component | File | Status |
|-----------|------|--------|
| Config | `core/config.py` — `SelfLearningConfig`, `SelfLearningPrivacyConfig` | Done |
| Local buffer | `core/database.py` — `collect_examples` table | Done |
| Sanitizer | `core/dataset_builder.py` — `DataSanitizer` (14 secret patterns, PII, browser data) | Done |
| Quality filter | `core/dataset_builder.py` — `QualityFilter` (min turns, success/failure) | Done |
| Signal extraction | `core/dataset_builder.py` — `_extract_signals()` (sentiment, denials, errors) | Done |
| Builder | `core/dataset_builder.py` — `DatasetBuilder` (buffer, upload, register, recover, flush) | Done |
| Agent integration | `core/agent.py` — hooks into task completion + shutdown | Done |
| Server: collect | `elophanto.com/app/api/collect/route.ts` | Done |
| Server: register | `elophanto.com/app/api/auth/register/route.ts` | Done |
| Server: recover | `elophanto.com/app/api/auth/recover/route.ts` | Done |
| Server: status | `elophanto.com/app/api/collect/status/route.ts` | Done |
| Server: HF push | `elophanto.com/app/api/cron/push-dataset/route.ts` (daily cron) | Done |
| Tests | `tests/test_core/test_dataset_builder.py` — 42 tests | Done |

### Remaining: Training Pipeline

Training infrastructure is solved: [HuggingFace Jobs + Unsloth](https://huggingface.co/blog/unsloth-jobs) provides managed GPU training with native dataset/model Hub integration at ~$1-4 per run.

Remaining prerequisites:

1. ~~Build agent-side dataset collection~~ **Done**
2. Accumulate sufficient interaction data from real agent usage (in progress — collecting now)
3. Set up HuggingFace dataset repo at `EloPhanto/dataset`
4. Set up HuggingFace model repos at `EloPhanto/base-model` and `EloPhanto/base-model-gguf`
5. Write the training script (UV script with inline deps for HF Jobs)
6. Validate end-to-end: dataset upload -> HF Job -> model push -> GGUF export -> Ollama pull
7. Define benchmark suite for evaluation
