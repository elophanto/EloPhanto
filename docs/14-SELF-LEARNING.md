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
┌──────────────────────────────────────────────────────────────────┐
│                    EloPhanto Self-Learning Loop                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐     │
│   │ Collect  │───►│  Store  │───►│  Train  │───►│ Publish │     │
│   │  Data    │    │ Dataset │    │ Unsloth │    │   HF    │     │
│   └────▲─────┘    └─────────┘    └─────────┘    └────┬────┘     │
│        │                                              │          │
│        │          ┌─────────┐    ┌─────────┐         │          │
│        └──────────│  Deploy │◄───│  Pull   │◄────────┘          │
│                   │  Ollama │    │  Model  │                    │
│                   └─────────┘    └─────────┘                    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

```
Detailed Flow:

Agent Interactions ──► Dataset Collector ──► Central Dataset Repo
                                                     │
                                            (size threshold met)
                                                     │
                                                     ▼
                                            Unsloth Fine-Tuning
                                            (QLoRA on base model)
                                                     │
                                                     ▼
                                            HuggingFace Upload
                                            (0xroyce/EloPhanto-Base-Model)
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

The dataset lives in a dedicated repository for versioning and accessibility:

```
Repository: github.com/0xroyce/elophanto-dataset
    (or HuggingFace Datasets: huggingface.co/datasets/0xroyce/elophanto-dataset)

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
| **Qwen3-Coder** | 30B-A3B | Latest coding model, MoE (only 3B active), fits consumer GPU |
| **Qwen3** | 4B / 8B / 14B | Strong reasoning + tool use, 2x faster with Unsloth |
| **DeepSeek-R1 Distill** | 7B / 14B | Reasoning-focused, chain-of-thought for planning |
| **Llama 4 Scout** | 17B-16E | Meta's latest MoE, strong general-purpose |
| **Gemma 3** | 4B / 12B | Fast, good at structured output, 3x faster with Flex-Attention |
| **GLM-4.7** | varies | Already used as EloPhanto's primary model via Z.ai |
| **gpt-oss** | 20B | OpenAI's open model, fits in 12.8GB VRAM |

The sweet spot depends on hardware: MoE models like Qwen3-30B-A3B only activate 3B parameters per token (fits ~17.5GB VRAM), while dense 7B-14B models offer simplicity. Unsloth supports all models that work in transformers.

### Unsloth Fine-Tuning

[Unsloth](https://github.com/unslothai/unsloth) provides 2x faster fine-tuning with 70% less VRAM via optimized kernels. Supports QLoRA, GRPO (reinforcement learning), vision models, and MoE architectures (12x faster MoE training).

```python
# Training configuration (conceptual)
training_config = {
    "base_model": "unsloth/Qwen3-8B-Instruct",
    "method": "QLoRA",
    "lora_r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    "max_seq_length": 8192,
    "per_device_train_batch_size": 4,
    "gradient_accumulation_steps": 4,
    "num_train_epochs": 3,
    "learning_rate": 2e-4,
    "warmup_ratio": 0.03,
    "lr_scheduler_type": "cosine",
    "bf16": True,
    "dataset_text_field": "text",
    "packing": True,
}
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

Training runs centrally on **[PrimeIntellect](https://www.primeintellect.ai/)** GPU servers — not on users' machines. This ensures:

- **Consistent environment** — Same hardware and software stack for every training run
- **Scalability** — Access to high-end GPU clusters for larger models
- **Reproducibility** — Central logs, checkpoints, and artifacts
- **No user burden** — Users contribute data, not compute

The pipeline is triggered centrally when dataset thresholds are met. Users receive the trained model via HuggingFace/Ollama — they never need to run training themselves.

## Model Registry

### HuggingFace Repository

Published to: **https://huggingface.co/0xroyce/EloPhanto-Base-Model**

```
0xroyce/EloPhanto-Base-Model/
├── README.md              # Model card (auto-generated)
├── config.json            # Model configuration
├── tokenizer.json         # Tokenizer
├── model.safetensors      # Model weights (or adapter weights)
├── adapter_config.json    # LoRA adapter config
└── training_metadata.json # Training details
```

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
Fallback 2: qwen2.5-coder:7b (base model via Ollama)
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
 │   2. FILTER & STORE                             │
 │   Quality filtering, privacy sanitization       │
 │   Push to central dataset repo                  │
 │                    │                            │
 │                    ▼                            │
 │   3. EVALUATE TRIGGER                           │
 │   Enough new data? Time threshold met?          │
 │                    │                            │
 │                    ▼                            │
 │   4. TRAIN                                      │
 │   Unsloth QLoRA fine-tuning on full dataset     │
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
  dataset_repo: "github.com/0xroyce/elophanto-dataset"
  model_repo: "huggingface.co/0xroyce/EloPhanto-Base-Model"
  auto_retrain: false               # Trigger training automatically
  retrain_threshold: 5000           # Min new examples before retraining
  privacy:
    strip_credentials: true
    strip_pii: true
    strip_file_contents: true
    exclude_browser_data: true
```

## Status

**Idea Phase** — This document captures the research direction for EloPhanto's self-learning capability. Implementation has not started. Key prerequisites:

1. Accumulate sufficient interaction data from real agent usage
2. Set up HuggingFace repository at `0xroyce/EloPhanto-Base-Model`
3. Set up dataset repository
4. Validate Unsloth training pipeline on a small dataset
5. Define benchmark suite for evaluation
