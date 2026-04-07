# Distribution Profiles

Profiles are predefined configurations for different EloPhanto use cases. Each profile specifies which tool groups to enable, which skills to prioritize, and config overrides applied on top of your base `config.yaml`.

## Available Profiles

| Profile       | Description                                                      |
|---------------|------------------------------------------------------------------|
| `developer`   | Coding, debugging, git, testing, code review, browser for docs   |
| `marketer`    | Social media, content, publishing, affiliate, commune, email     |
| `researcher`  | Web search, documents, knowledge, context store, email           |
| `trader`      | Payments, Solana, web search, browser for market data            |
| `minimal`     | Core system tools only (file, shell, knowledge), nothing else    |

## Usage

### CLI flag

```bash
elophanto gateway --profile developer
elophanto chat --profile researcher
```

### Config file

Add to your `config.yaml`:

```yaml
profile: marketer
```

The `--profile` CLI flag takes precedence over the config file value.

## Profile Format

Each profile is a YAML file with this structure:

```yaml
name: Profile Name
description: One-line description of the profile purpose
tool_groups:
  - system
  - browser
  - knowledge
skills_priority:
  - skill-name-1
  - skill-name-2
config_overrides:
  section_name:
    key: value
```

### Fields

- **name**: Human-readable profile name.
- **description**: What this profile is for.
- **tool_groups**: List of tool group identifiers to enable. Tools not in these groups are excluded.
- **skills_priority**: Ordered list of skill names to prioritize during task execution.
- **config_overrides**: Nested dictionary of config section overrides. These are merged on top of your base `config.yaml` values. Supports any config section (`shell`, `browser`, `payments`, `email`, etc.).

## Creating Custom Profiles

1. Create a new YAML file in `profiles/` (e.g., `profiles/ops.yaml`).
2. Define `name`, `description`, `tool_groups`, `skills_priority`, and `config_overrides`.
3. Use it with `--profile ops` or `profile: ops` in config.

Example custom profile:

```yaml
# profiles/ops.yaml
name: DevOps
description: Infrastructure, deployment, monitoring, and CI/CD tools
tool_groups:
  - system
  - browser
  - knowledge
  - context
skills_priority:
  - writing-plans
  - verification-before-completion
config_overrides:
  shell:
    timeout: 120
  browser:
    enabled: true
    headless: true
  deployment:
    enabled: true
```

## Override Precedence

Config values are resolved in this order (last wins):

1. Default values (dataclass defaults)
2. `config.yaml` values
3. Profile `config_overrides`
4. Environment variable overrides
