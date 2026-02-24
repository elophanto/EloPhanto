# EloPhanto — LLM Routing

## Overview

EloPhanto uses multiple LLM models for different purposes. Not every task needs the most powerful (and expensive) model. The routing layer decides which model to use based on the task type, user configuration, and available providers.

The routing layer is built on `litellm` for OpenRouter and Ollama, with a custom adapter for Z.ai/GLM (since GLM has OpenAI-compatible endpoints but requires specific message formatting rules).

## Providers

### OpenRouter

Cloud-hosted models accessed via API. Supports Claude, GPT, Gemini, Llama, Mistral, and dozens of others through a single API key.

- **Pros**: Access to the strongest models (Claude Opus, GPT-4o), no local GPU needed, high reliability
- **Cons**: Costs money per token, requires internet, data leaves the machine
- **Setup**: User provides an OpenRouter API key during initial setup
- **Base URL**: `https://openrouter.ai/api/v1`

### Z.ai (GLM Models)

Cloud-hosted GLM models from Zhipu AI, accessed via Z.ai's API. Particularly strong for coding tasks with a dedicated Coding Plan that offers 3× usage at roughly 1/7 the cost.

- **Pros**: Excellent coding performance (GLM-4.7), very cost-effective with the Coding Plan, OpenAI-compatible API format, good for code generation and review tasks
- **Cons**: Requires internet, no embeddings API, specific message formatting constraints (see below), separate API key from OpenRouter
- **Setup**: User provides a Z.ai API key. Optionally subscribes to the GLM Coding Plan for cost savings.
- **Base URL (Coding Plan)**: `https://api.z.ai/api/coding/paas/v4`
- **Base URL (Pay-as-you-go)**: `https://api.z.ai/api/paas/v4`
- **API Key management**: `https://z.ai/manage-apikey/apikey-list`
- **Coding Plan subscription**: `https://z.ai/subscribe`

#### Available GLM Models

| Model ID | Name | Best For |
|---|---|---|
| `glm-5` | GLM-5 | Next generation, general purpose |
| `glm-4.7` | GLM-4.7 | Coding (recommended for code tasks) |
| `glm-4.7-flash` | GLM-4.7-Flash | Fast coding, lighter tasks |
| `glm-4-plus` | GLM-4-Plus | Previous generation, general purpose |

#### GLM Message Constraints

The Z.ai API has stricter message formatting rules than OpenRouter or Ollama. The adapter must enforce these to avoid error 1214:

1. System message must be at index 0 only (no system messages elsewhere in the conversation)
2. Assistant messages with `tool_calls` must use `content: null` (not empty string `""`)
3. Tool results must have `tool_call_id` matching a preceding tool call
4. No non-tool messages between an assistant's `tool_calls` and its tool results
5. One tool result per `tool_call_id` (no duplicates)
6. There must be at least one user message in the sequence

The EloPhanto GLM adapter handles this automatically — it reformats the agent's message history to comply with these constraints before sending to the API. The agent itself doesn't need to be aware of these rules.

#### Required Headers

```
Content-Type: application/json
Authorization: Bearer <api_key>
Accept-Language: en-US,en
```

The `Accept-Language` header is important — without it, responses may default to Chinese.

### Ollama

Locally-hosted models running on the user's machine.

- **Pros**: Free, private (no data leaves machine), works offline
- **Cons**: Requires GPU for good performance, limited model quality, slower for large models
- **Setup**: User installs Ollama separately. EloPhanto detects available models automatically.
- **Base URL**: `http://localhost:11434`

### Provider Priority

Users configure a priority order in the config. Default:

1. **Ollama** (if a capable model is available for the task type) — prefer local for privacy and cost
2. **Z.ai/GLM** (for coding tasks specifically) — excellent quality/cost ratio with Coding Plan
3. **OpenRouter** — strongest models, fallback for everything else

The user can override this to any custom priority order, or set per-task-type provider preferences.

## Task Types and Model Selection

### Planning and Reasoning

The agent's highest-stakes cognitive work: understanding goals, breaking them into steps, deciding which tools to use, handling ambiguity.

- **Recommended**: Strongest available model (Claude Opus via OpenRouter, GPT-4o, or GLM-5)
- **Local alternative**: Qwen 2.5 72B, Llama 3.1 70B (if user has sufficient GPU)
- **Minimum viable**: Qwen 2.5 32B, Llama 3.1 8B (quality degrades significantly)

### Code Generation

Writing plugins, tests, scripts. Requires strong coding ability and understanding of project patterns.

- **Recommended**: GLM-4.7 via Z.ai Coding Plan (best cost/quality ratio for code), Claude Sonnet via OpenRouter, DeepSeek Coder v2
- **Local alternative**: Qwen 2.5 Coder 32B, DeepSeek Coder v2 16B
- **Note**: Code generation benefits from high context windows. Prefer models with 32k+ context.
- **Note**: The Z.ai Coding Plan makes GLM-4.7 extremely cost-effective for high-volume code generation (self-development pipeline generates a lot of code).

### Code Review

Reviewing self-generated code (Stage 6 of the self-development pipeline). Ideally uses a different model than the one that wrote the code, to catch different types of errors.

- **Strategy**: If code was written by Model A, review with Model B
- **Example combinations**:
  - Write with GLM-4.7 (Z.ai) → review with Claude Sonnet (OpenRouter)
  - Write with Claude Sonnet → review with GLM-4.7
  - Write with Qwen Coder (local) → review with GLM-4.7 (Z.ai) or Claude (OpenRouter)
- **Principle**: Different model architectures have different blind spots. Cross-architecture review catches more bugs.

### Analysis and Summarization

Processing text, summarizing emails, analyzing documents. Moderate complexity.

- **Recommended**: Claude Sonnet (OpenRouter), GPT-4o-mini, GLM-4.7-Flash (Z.ai)
- **Local alternative**: Qwen 2.5 14B, Llama 3.1 8B
- **Note**: These tasks are often high-volume. GLM-4.7-Flash via Coding Plan is cost-effective here.

### Simple Tasks

Formatting, classification, extraction, template filling. Low complexity.

- **Recommended**: Cheapest available — GLM-4.7-Flash (Z.ai), GPT-4o-mini (OpenRouter)
- **Local alternative**: Any local model, even small ones (Llama 3.2 3B, Phi-3)
- **Note**: Speed matters more than quality here.

### Embeddings

Converting text chunks to vectors for the knowledge system.

- **Cloud** (default): `google/gemini-embedding-001` via OpenRouter — fast, cheap, high-quality multilingual embeddings
- **Local fallback**: `nomic-embed-text` or `mxbai-embed-large` via Ollama — free, private, works offline
- **Note**: Z.ai does NOT offer an embeddings API. Embeddings are handled by OpenRouter or Ollama.
- **Auto mode** (default): Uses OpenRouter if an API key is configured, otherwise falls back to Ollama. Configurable via `knowledge.embedding_provider` in `config.yaml`.

## Routing Logic

The router uses this decision process:

```
1. Determine task type (from the llm_call tool's task_type parameter)
2. Check if a specific model was requested (override)
   → If yes, use that model via its provider
3. Check user's per-task-type configuration
   → If configured, use that model/provider
4. Apply task-type defaults:
   → coding/review: prefer Z.ai GLM-4.7 (if enabled and Coding Plan active)
   → planning: prefer strongest cloud model (OpenRouter)
   → simple: prefer cheapest option (local > Z.ai Flash > OpenRouter mini)
   → embedding: handled separately (OpenRouter or Ollama, see knowledge config)
5. Check provider priority order
   → For each provider in priority order:
     - Is the provider enabled and reachable?
     - Is a suitable model available for this task type?
     → If yes, use it
6. Fallback: use whatever is available, warn if quality is suboptimal
```

### Provider Adapter Architecture

Since we have three providers with different APIs:

```
┌────────────────────────────────────┐
│           LLM Router               │
│  (selects provider + model)        │
├────────────┬───────────┬───────────┤
│ litellm    │ Z.ai      │ litellm   │
│ adapter    │ adapter   │ adapter   │
│            │ (custom)  │           │
├────────────┼───────────┼───────────┤
│ OpenRouter │ Z.ai API  │ Ollama    │
└────────────┴───────────┴───────────┘
```

- **OpenRouter + Ollama**: Handled by `litellm` natively (unified API)
- **Z.ai/GLM**: Custom adapter that wraps the OpenAI-compatible API with GLM-specific message formatting, header requirements, and error handling

The custom Z.ai adapter:
1. Accepts the same input format as litellm (standard messages array)
2. Reformats messages to comply with GLM constraints (system at index 0 only, null content for tool_calls, etc.)
3. Adds required headers (`Accept-Language: en-US,en`)
4. Makes the API call to the appropriate base URL (Coding Plan or pay-as-you-go)
5. Returns the response in the same format as litellm

This means the agent core never knows or cares which provider is being used — it always works with the same interface.

## Configuration

In `config.yaml`:

```yaml
llm:
  providers:
    openrouter:
      api_key_ref: "openrouter_api_key"  # reference to vault secret
      enabled: true
    
    zai:
      api_key_ref: "zai_api_key"  # reference to vault secret
      enabled: true
      coding_plan: true  # if user has the Coding Plan subscription
      base_url_coding: "https://api.z.ai/api/coding/paas/v4"
      base_url_paygo: "https://api.z.ai/api/paas/v4"
      default_model: "glm-4.7"
    
    ollama:
      base_url: "http://localhost:11434"
      enabled: true

  provider_priority:
    - ollama
    - zai
    - openrouter

  routing:
    planning:
      preferred_provider: openrouter
      models:                                  # provider → model map
        openrouter: "anthropic/claude-sonnet-4.6"
        zai: "glm-5"
        ollama: "qwen2.5:32b"
    coding:
      preferred_provider: zai
      models:
        zai: "glm-4.7"
        openrouter: "qwen/qwen3.5-plus-02-15"
        ollama: "qwen2.5-coder:32b"
    analysis:
      preferred_provider: openrouter
      models:
        openrouter: "google/gemini-3.1-pro-preview"
        zai: "glm-4.7"
        ollama: "qwen2.5:14b"
    simple:
      preferred_provider: openrouter
      models:
        openrouter: "minimax/minimax-m2.5"
        zai: "glm-4.7"
        ollama: "llama3.2:3b"

  budget:
    daily_limit_usd: 10.00
    per_task_limit_usd: 2.00
    warn_at_percent: 80
```

## Cost Tracking

The router tracks token usage and estimated costs for every cloud LLM call:

- Running total per day, per task, per model, per provider
- Stored in the database for historical analysis
- The agent can query its own spending history
- Budget limits are enforced — if the daily limit is hit, the router switches to local-only mode and notifies the user
- Z.ai Coding Plan usage is tracked separately (since pricing differs from pay-as-you-go)

## Model Discovery

On startup and periodically, the router:

1. Queries Ollama for available local models (`ollama list`)
2. Validates that configured OpenRouter models are accessible (quick API check)
3. Validates Z.ai connectivity and confirms which plan is active (Coding Plan vs pay-as-you-go)
4. Updates an internal model registry with capabilities (context window size, strengths, cost per token)
5. Logs any mismatches between config and reality (e.g., configured local model not installed, Z.ai key expired)

## Cross-Provider Review Strategy

The `cross_provider` review strategy deserves special attention. When the self-development pipeline generates code:

1. The router records which provider/model wrote the code
2. For the review stage, it automatically selects a different provider
3. Preference order for cross-review:
   - If written by Z.ai → review by OpenRouter (Claude or GPT)
   - If written by OpenRouter → review by Z.ai (GLM-4.7)
   - If written locally (Ollama) → review by either cloud provider
   - If only one cloud provider is available → use a different model from the same provider
   - If only local is available → use a different local model family

This maximizes the chance of catching bugs because different model architectures have different failure modes.

## Adaptive Routing (Future Enhancement)

Over time, EloPhanto can learn which models perform best for which tasks based on outcomes:

- Track success/failure rates per model per task type
- Track user satisfaction (did the user accept the output or ask for changes?)
- Track cost-per-successful-outcome (not just cost-per-token)
- Gradually adjust routing preferences based on data
- Document findings in `/knowledge/learned/patterns/model_performance.md`

This is a natural candidate for self-development — the agent can build this capability once it has enough historical data.
