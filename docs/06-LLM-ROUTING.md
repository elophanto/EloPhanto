# EloPhanto — LLM Routing

## Overview

EloPhanto uses multiple LLM models for different purposes. Not every task needs the most powerful (and expensive) model. The routing layer decides which model to use based on the task type, user configuration, and available providers.

The routing layer is built on `litellm` for OpenRouter, OpenAI, and Ollama, with custom adapters for Z.ai/GLM (which requires specific message formatting) and Kimi/Moonshot AI (routed through the Kilo Code AI Gateway).

## Providers

### OpenAI

Direct access to OpenAI's models (GPT-5.4, o3, o1) via the official API.

- **Pros**: Access to latest GPT models, strong tool use and reasoning, reliable infrastructure
- **Cons**: Costs money per token, requires internet, data leaves the machine
- **Setup**: User provides an OpenAI API key during initial setup
- **Default model**: `gpt-5.4`
- **Base URL**: `https://api.openai.com/v1` (default, configurable for Azure or proxies)

#### Available OpenAI Models

| Model ID | Name | Best For |
|---|---|---|
| `gpt-5.4` | GPT-5.4 | Latest generation, general purpose (recommended) |
| `gpt-4.1` | GPT-4.1 | Previous generation, general purpose |
| `o3` | o3 | Advanced reasoning tasks |
| `o1` | o1 | Complex reasoning and analysis |

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

### Kimi / Moonshot AI (via Kilo Code Gateway)

Cloud-hosted Kimi K2.5 from Moonshot AI, accessed via the Kilo Code AI Gateway. Kimi K2.5 is a native multimodal vision model with strong coding and agentic capabilities.

- **Pros**: Native multimodal vision (text + image input), strong coding ability, OpenAI-compatible API, competitive pricing via Kilo Gateway
- **Cons**: Requires internet, requires Kilo Code subscription for the gateway API key
- **Setup**: User gets a Kilo Gateway API key from [app.kilo.ai](https://app.kilo.ai). The adapter maps internal model names (e.g. `kimi-k2.5`) to gateway model IDs (`moonshotai/kimi-k2.5`) automatically.
- **Base URL**: `https://api.kilo.ai/api/gateway`
- **Kilo Gateway docs**: [kilo.ai/docs/gateway](https://kilo.ai/docs/gateway)
- **Environment variable**: `KIMI_API_KEY`

#### Available Kimi Models

| Model ID (internal) | Gateway Model ID | Best For |
|---|---|---|
| `kimi-k2.5` | `moonshotai/kimi-k2.5` | Multimodal vision + coding (recommended) |
| `kimi-k2-thinking-turbo` | `moonshotai/kimi-k2.5` | Simple/fast tasks (maps to k2.5 on gateway) |

#### Kilo Code Gateway

The Kilo AI Gateway is a universal AI inference API that is fully OpenAI-compatible. Unlike the direct Moonshot API (`api.moonshot.ai`), the gateway uses JWT tokens from [app.kilo.ai](https://app.kilo.ai) for authentication and model IDs in `provider/model` format (e.g. `moonshotai/kimi-k2.5`). The adapter handles this mapping transparently — the rest of EloPhanto works with short model names like `kimi-k2.5`.

#### Approximate Cost (Kilo Gateway)

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|---|---|---|
| `kimi-k2.5` | $0.45 | $2.20 |

### Ollama

Locally-hosted models running on the user's machine.

- **Pros**: Free, private (no data leaves machine), works offline
- **Cons**: Requires GPU for good performance, limited model quality, slower for large models
- **Setup**: User installs Ollama separately. EloPhanto detects available models automatically.
- **Base URL**: `http://localhost:11434`

### Provider Priority

Recommended order (matches `config.demo.yaml`):

1. **OpenRouter** — access to all frontier models via a single key. Primary provider for all task types with `hunter-alpha` as the recommended model
2. **Z.ai/GLM** — excellent coding quality/cost ratio with the Coding Plan (unlimited GLM-4.7/GLM-5 at flat monthly rate). Fallback for all tasks
3. **OpenAI** — direct access to GPT-5.4. Enable if you need OpenAI-specific features
4. **Kimi** — native multimodal vision model via Kilo Gateway. Enable for vision-heavy workloads
5. **Ollama** — local, free, private. Useful for embeddings and offline use

The user can override this to any custom priority order, or set per-task-type provider preferences.

> **Recommended setup**: See `config.demo.yaml` for the full recommended configuration with all providers, models, and feature settings.

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

Since we have five providers with different APIs:

```
┌────────────────────────────────────────────────────────────────┐
│                        LLM Router                              │
│                 (selects provider + model)                     │
├────────────┬───────────┬───────────┬───────────┬──────────────┤
│ litellm    │ Z.ai      │ Kimi      │ litellm   │ litellm      │
│ adapter    │ adapter   │ adapter   │ adapter   │ adapter      │
│            │ (custom)  │ (custom)  │           │              │
├────────────┼───────────┼───────────┼───────────┼──────────────┤
│ OpenRouter │ Z.ai API  │ Kilo GW   │ OpenAI    │ Ollama       │
└────────────┴───────────┴───────────┴───────────┴──────────────┘
```

- **OpenRouter + OpenAI + Ollama**: Handled by `litellm` natively (unified API)
- **Z.ai/GLM**: Custom adapter that wraps the OpenAI-compatible API with GLM-specific message formatting, header requirements, and error handling
- **Kimi**: Custom adapter that routes through the Kilo Code AI Gateway. Maps internal model names to gateway model IDs (`kimi-k2.5` → `moonshotai/kimi-k2.5`) and uses JWT token auth. No special message formatting needed — the gateway is fully OpenAI-compatible

The custom Z.ai adapter:
1. Accepts the same input format as litellm (standard messages array)
2. Reformats messages to comply with GLM constraints (system at index 0 only, null content for tool_calls, etc.)
3. Adds required headers (`Accept-Language: en-US,en`)
4. Makes the API call to the appropriate base URL (Coding Plan or pay-as-you-go)
5. Returns the response in the same format as litellm

This means the agent core never knows or cares which provider is being used — it always works with the same interface.

## Configuration

> **Full recommended config**: Copy `config.demo.yaml` to `config.yaml` — it includes all providers, recommended models, vision routing, browser settings, and feature flags ready to use.

Routing section reference (recommended setup from `config.demo.yaml`):

```yaml
llm:
  providers:
    openrouter:
      api_key: "YOUR_OPENROUTER_KEY"
      enabled: true
      base_url: "https://openrouter.ai/api/v1"
    zai:
      api_key: "YOUR_ZAI_KEY"
      enabled: true
      coding_plan: true
      base_url_coding: "https://api.z.ai/api/coding/paas/v4"
      base_url_paygo: "https://api.z.ai/api/paas/v4"
      default_model: "glm-4.7"
    openai:
      api_key: "YOUR_OPENAI_KEY"
      enabled: false
      default_model: "gpt-5.4"
    kimi:
      api_key: "YOUR_KILO_API_KEY"
      enabled: false
      base_url: "https://api.kilo.ai/api/gateway"
      default_model: "kimi-k2.5"
    ollama:
      base_url: "http://localhost:11434"
      enabled: true

  # Auto-routes to vision model when messages contain image_url blocks
  vision_model: "openrouter/x-ai/grok-4.1-fast"

  provider_priority:
    - openrouter
    - zai
    - openai
    - kimi

  routing:
    planning:
      preferred_provider: openrouter
      reasoning_effort: high       # OpenRouter: extra_body={"reasoning":{"effort":"high"}}; OpenAI: reasoning_effort kwarg
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-5"
        kimi: "kimi-k2.5"
        openai: "gpt-5.4"
        ollama: "nomic-embed-text:latest"
    coding:
      preferred_provider: openrouter
      reasoning_effort: medium
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-4.7"
        kimi: "kimi-k2.5"
        openai: "gpt-5.4"
        ollama: "nomic-embed-text:latest"
    analysis:
      preferred_provider: openrouter
      reasoning_effort: low
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-4.7"
        kimi: "kimi-k2.5"
        openai: "gpt-5.4"
        ollama: "nomic-embed-text:latest"
    simple:
      preferred_provider: openrouter
      reasoning_effort: minimal    # or "none" to disable extended thinking entirely
      models:
        openrouter: "openrouter/hunter-alpha"
        zai: "glm-4.7"
        kimi: "kimi-k2-thinking-turbo"
        ollama: "nomic-embed-text:latest"

  budget:
    daily_limit_usd: 100.00
    per_task_limit_usd: 20.00
```

### Vision Routing

When any message in the conversation history contains an `image_url` content block (browser screenshots, Telegram images, etc.), the router automatically uses `llm.vision_model` instead of the normal priority chain. Set this to any vision-capable OpenRouter model:

```yaml
llm:
  vision_model: "openrouter/x-ai/grok-4.1-fast"   # recommended
  # vision_model: "openrouter/google/gemini-2.0-flash-001"  # alternative
```

Leave empty (`""`) to disable — images will be stripped before sending to text-only providers.

### Reasoning Effort

Each task type supports an optional `reasoning_effort` field that controls how much "thinking budget" the model uses:

| Value | Behaviour |
|-------|-----------|
| `high` | Maximum extended thinking (best quality, slowest, most expensive) |
| `medium` | Balanced reasoning budget |
| `low` | Light reasoning pass |
| `minimal` | Minimal thinking, fastest response |
| `""` (empty) | No effort hint sent — provider defaults apply |

**OpenRouter**: sent as `extra_body={"reasoning": {"effort": "<value>"}}` — activates extended thinking on capable models (e.g. hunter-alpha, claude-opus).

**OpenAI**: sent as the `reasoning_effort` kwarg — applies to o-series reasoning models (o3, o1).

For providers that don't support reasoning effort (Z.ai, Kimi, Ollama) the field is silently ignored.

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
2. Validates OpenAI connectivity (`GET /v1/models` with Bearer token)
3. Validates that configured OpenRouter models are accessible (quick API check)
4. Validates Z.ai connectivity and confirms which plan is active (Coding Plan vs pay-as-you-go)
5. Validates Kimi connectivity via Kilo Gateway (minimal chat completion with `max_tokens: 1`)
6. Updates an internal model registry with capabilities (context window size, strengths, cost per token)
7. Logs any mismatches between config and reality (e.g., configured local model not installed, Z.ai key expired)

**Dashboard health indicators**: The startup dashboard shows all configured providers with color-coded status — green (●) for healthy providers that passed the health check, yellow (●) for degraded providers that are configured and enabled but failed the startup health check (still eligible for routing — cloud providers auto-recover after 60s cooldown).

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

## Provider Transparency

The router tracks per-provider behavior via `core/provider_tracker.py` (see [27-SECURITY-HARDENING.md](27-SECURITY-HARDENING.md) Gap 5). LLM providers can silently truncate, censor, or refuse responses — the transparency layer detects and surfaces this.

### What's Tracked

Every LLM call records a `ProviderEvent` with:

- **finish_reason**: `stop` (normal), `length` (truncated), `content_filter` (censored), `error` (failed)
- **latency_ms**: Wall-clock time for the call
- **fallback_from**: Which provider(s) failed before this one succeeded
- **suspected_truncated**: Heuristic detection — true if finish_reason=length/content_filter, or if response ends mid-sentence with >500 output tokens

### Per-Provider Stats

The `ProviderTracker` aggregates events into per-provider summaries:

| Stat | Description |
|------|-------------|
| `total_calls` | Total LLM calls to this provider |
| `failures` | Calls with finish_reason=error |
| `truncations` | Calls flagged as suspected_truncated |
| `content_filters` | Calls with finish_reason=content_filter |
| `fallbacks_to` | Times this provider was the fallback target |
| `avg_latency_ms` | Average wall-clock latency |

### Runtime State

Provider stats are surfaced in `<runtime_state>` as a `<providers>` XML block, giving the LLM ground truth about provider health:

```xml
<providers>
  <provider name="openrouter" calls="42" failures="1" truncations="0" avg_latency_ms="1200"/>
  <provider name="zai" calls="30" failures="3" truncations="2" avg_latency_ms="800"/>
</providers>
```

### Database Persistence

Four columns on the `llm_usage` table store per-call transparency data: `finish_reason`, `latency_ms`, `fallback_from`, `suspected_truncated`. Added via idempotent ALTER TABLE migrations in `core/database.py`.

### Fallback Recording

When the router falls back from one provider to another (e.g., Z.ai fails then OpenRouter succeeds), the successful `LLMResponse` carries `fallback_from="zai"` and a failure `ProviderEvent` is recorded for the failed provider.

## Tool Profiles

When the agent has many tools loaded, sending all of them on every LLM call wastes tokens and can hit provider limits (e.g. OpenAI's 128-tool cap). Tool profiles solve this by selecting only the relevant tool groups for each task type.

Each tool declares a **group** (`system`, `browser`, `desktop`, `knowledge`, `skills`, `data`, `selfdev`, `goals`, `comms`, `payments`, `identity`, `documents`, `media`, `social`, `infra`, `org`, `swarm`, `mcp`, `scheduling`, `mind`, `hub`). Profiles are named sets of groups:

| Profile | Groups included |
|---------|----------------|
| `minimal` | system, knowledge, data, skills |
| `coding` | minimal + selfdev, goals |
| `browsing` | minimal + browser |
| `desktop_profile` | minimal + desktop |
| `comms` | minimal + comms, identity |
| `devops` | minimal + infra, swarm |
| `full` | all groups |

The router maps each task type to a profile (`planning` → `full`, `coding` → `coding`, `analysis` → `minimal`, `simple` → `minimal`). Override per-task with `tool_profile` in routing config, or define custom profiles under `llm.tool_profiles`.

Provider-level controls:
- `max_tools` — hard cap on tools sent (OpenAI defaults to 128)
- `tool_deny` — groups to always exclude for a provider

If filtered tools still exceed `max_tools`, a priority-based trimmer drops low-priority groups first, then trims largest-schema tools.

See [36-TOOL-PROFILES.md](36-TOOL-PROFILES.md) for the full design document.

## Adaptive Routing (Future Enhancement)

Over time, EloPhanto can learn which models perform best for which tasks based on outcomes:

- Track success/failure rates per model per task type
- Track user satisfaction (did the user accept the output or ask for changes?)
- Track cost-per-successful-outcome (not just cost-per-token)
- Gradually adjust routing preferences based on data
- Document findings in `/knowledge/learned/patterns/model_performance.md`

This is a natural candidate for self-development — the agent can build this capability once it has enough historical data.
