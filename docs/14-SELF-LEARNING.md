# EloPhanto — Self-Learning Model Pipeline

> **Status: Idea Phase** — This document describes a planned research direction, not yet implemented.

## Overview

EloPhanto currently relies on external LLM providers (Z.ai, OpenRouter) and local generic models (Ollama). The next step is training a **custom EloPhanto base model** — fine-tuned specifically for agent tasks: tool selection, multi-step planning, code generation, and self-reflection.

The model is trained on EloPhanto's own interaction data, published to HuggingFace, deployed locally via Ollama, and continuously improved as new data accumulates. Each training cycle produces a better model that understands EloPhanto's tool system, permission model, and task patterns.

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

**Agent-side flow** (runs locally):

1. After each successful task, the agent serializes the interaction into the training format
2. Local sanitizer strips credentials, PII, secrets, and browser data
3. Quality filter drops trivial/failed/too-short interactions
4. If `self_learning.collect_data: true` and user has opted in, the agent POSTs the sanitized example to the collection API
5. Examples are batched locally and uploaded periodically (not per-interaction) to minimize network overhead

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
    "task_type": "file_analysis",
    "tools_used": ["shell_execute"],
    "success": true,
    "duration_seconds": 4.2,
    "model_used": "glm-4.7",
    "timestamp": "2026-02-18T10:30:00Z"
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

Not all interactions produce good training data. Filter criteria:

| Filter | Purpose |
|--------|---------|
| **Success only** | Only include tasks that completed successfully |
| **Min turns** | Exclude trivial single-turn interactions |
| **No errors** | Exclude conversations with unrecovered errors |
| **Tool accuracy** | Only include when the right tool was selected |
| **Deduplication** | Remove near-identical conversations (embedding similarity > 0.95) |
| **Length bounds** | Drop extremely short or excessively long examples |

### Privacy & Security

Training data must be sanitized before storage:

- **Strip credentials** — Remove vault references, API keys, tokens
- **Strip PII** — Remove usernames, emails, file paths with personal info
- **Strip secrets** — Remove anything matching secret patterns (regex-based)
- **Redact file contents** — Replace sensitive file contents with placeholders
- **No browser data** — Exclude screenshots, cookies, session data
- **Configurable opt-out** — Users can disable data collection entirely

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
# config.yaml (future)
self_learning:
  enabled: false                    # Opt-in
  collect_data: true                # Capture interactions for training
  collect_api: "https://elophanto.com/api/collect"
  collect_key_ref: elophanto_collect_key  # Vault key for collection API auth
  batch_size: 10                    # Upload every N examples (not per-interaction)
  dataset_repo: "EloPhanto/dataset"              # HuggingFace Datasets repo
  model_repo: "EloPhanto/base-model"             # HuggingFace model repo
  gguf_repo: "EloPhanto/base-model-gguf"         # GGUF export repo
  hf_token_ref: hf_token           # Vault key for HuggingFace write token
  training:
    gpu_flavor: a10g-small          # HF Jobs GPU tier
    timeout_hours: 4                # Max training job duration
    base_model: "unsloth/Qwen3-4B-Instruct"
  auto_retrain: false               # Trigger training automatically
  retrain_threshold: 5000           # Min new examples before retraining
  privacy:
    strip_credentials: true
    strip_pii: true
    strip_file_contents: true
    exclude_browser_data: true
```

## Status

**Idea Phase** — This document captures the research direction for EloPhanto's self-learning capability. Implementation has not started.

Training infrastructure is solved: [HuggingFace Jobs + Unsloth](https://huggingface.co/blog/unsloth-jobs) provides managed GPU training with native dataset/model Hub integration at ~$1-4 per run.

Key prerequisites:

1. Accumulate sufficient interaction data from real agent usage
2. Set up HuggingFace dataset repo at `EloPhanto/dataset`
3. Set up HuggingFace model repos at `EloPhanto/base-model` and `EloPhanto/base-model-gguf`
4. Write the training script (UV script with inline deps for HF Jobs)
5. Validate end-to-end: dataset upload -> HF Job -> model push -> GGUF export -> Ollama pull
6. Define benchmark suite for evaluation
