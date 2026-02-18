# EloPhanto — Self-Development Pipeline

## Overview

The self-development pipeline is what makes EloPhanto different from a static agent. When EloPhanto encounters a task it cannot perform with its existing tools, it can design, build, test, and deploy new capabilities — and then immediately use them.

This pipeline applies to two categories of work:

1. **Plugin creation**: Building entirely new tools (e.g., a Gmail integration, a Slack bot, a PDF parser)
2. **Core modification**: Changing EloPhanto's own behavior — its planning logic, prompt templates, routing rules, memory system, or any other internal module

Both follow the same pipeline, but core modifications have stricter safety requirements.

## The Pipeline

### Stage 1: Recognition

The agent recognizes it lacks a needed capability. This happens during the planning phase of the core loop when:

- No existing tool matches the required action
- An existing tool failed and the agent determines it needs a different approach
- The user explicitly asks for a new capability
- The agent identifies an optimization opportunity in its own behavior

At this point, the agent logs the capability gap and enters the self-development sub-loop.

### Stage 2: Research

Before writing any code, the agent gathers information.

**Sources, in priority order:**

1. Its own knowledge base (`/knowledge/`) — has it encountered this before? Are there relevant docs?
2. Its own source code — how do similar tools work? What patterns does the project use?
3. Its conventions file (`/knowledge/system/conventions.md`) — what are the coding standards?
4. External resources (via browser or web search) — API documentation, library references, examples
5. Long-term memory — has it tried something similar before? What worked or failed?

**Output of this stage**: A research summary saved as a temporary markdown file. This ensures the agent has all relevant context before it starts designing.

### Stage 3: Design

The agent writes a design document before any implementation. This document is saved to `/knowledge/system/designs/` and includes:

- **Goal**: What the new capability does, in plain language
- **Approach**: How it will be implemented
- **Interface**: The tool's name, description, input schema, output schema
- **Dependencies**: What packages or APIs are needed
- **Edge cases**: What can go wrong, and how the tool should handle it
- **Security considerations**: Does this tool handle sensitive data? Does it have side effects?
- **Test plan**: What tests will verify correctness

For core modifications, the design document also includes:

- **Impact analysis**: What other parts of the system are affected
- **Rollback plan**: How to revert if the change causes problems
- **Before/after behavior**: Concrete examples of how behavior changes

If the agent is in "Ask Always" or "Smart Auto" mode, the design document is presented to the user for approval before proceeding to implementation. The user can approve, request changes, or reject.

### Stage 4: Implementation

The agent writes the code. Key requirements:

**For plugins:**
- Must follow the tool interface (name, description, schema, execute function)
- Must be a self-contained module in `/plugins/<name>/`
- Must include type hints (Python) or JSDoc (JavaScript)
- Must handle errors gracefully — return error information, never crash
- Must not hardcode secrets — use the `secrets_manager` tool for any credentials
- Must follow patterns established in `/knowledge/system/conventions.md`

**For core modifications:**
- Changes are applied to a copy of the affected file first (not in-place)
- The agent generates a git-style diff showing exactly what changed
- Changes must preserve all existing tests (no removing tests to make changes pass)

**Language choice:**
- Python is the default for plugins that interact with the local system, APIs, or data processing
- TypeScript is used for the Node.js browser bridge and plugins that benefit from the Node.js ecosystem
- The agent should document its language choice rationale in the design doc
- Mixed-language plugins are allowed but should be avoided unless necessary. If used, the plugin must include setup scripts for both runtimes.

### Stage 5: Testing

This is non-negotiable. Every piece of self-developed code must pass tests before deployment.

**Test types required:**

1. **Unit tests**: Test the tool in isolation. Mock external dependencies. Verify input validation, output format, error handling. Minimum: one test per happy path, one per error path, one per edge case identified in the design.

2. **Integration tests** (when applicable): Test the tool with real external services in a safe way. For example, a Gmail tool should be able to connect and read (but not send) in test mode. A shell tool should be tested with safe commands.

3. **Lint/format check**: Code must pass `ruff` (Python) or `eslint` (JavaScript) with the project's configuration.

4. **Type checking**: Must pass `mypy` (Python) or `tsc --noEmit` (TypeScript) if applicable.

**For core modifications, additionally:**

5. **Full regression suite**: Run the entire project test suite, not just the new/modified tests. The change must not break anything.

6. **Behavioral tests**: If the change alters agent behavior (e.g., how it plans, how it routes models), run a set of predefined test scenarios and compare outputs before/after.

**Test execution:**

- Tests run in a subprocess with a timeout (default 60 seconds per test file)
- Test output (pass/fail, errors, coverage) is captured and stored
- If any test fails, the pipeline stops and the agent must fix the issue before retrying
- Maximum retry attempts: 3. After 3 failures, the agent logs the failure, documents what went wrong in `/knowledge/learned/failures/`, and reports to the user

### Stage 6: Self-Review

After tests pass, the agent reviews its own code. This is a separate LLM call — ideally using a different (stronger) model than the one that wrote the code.

**Review checklist:**

- Does the code do what the design document says?
- Are there security issues? (injection, credential exposure, path traversal, etc.)
- Are there resource leaks? (unclosed files, connections, etc.)
- Is error handling comprehensive?
- Are edge cases covered?
- Is the code readable and well-structured?
- Does it follow project conventions?
- Could it cause performance issues? (memory, CPU, network)
- For core modifications: could this change break the permission system, the safety blacklists, or the recovery mechanisms?

**Review output**: A structured review with pass/fail per checklist item and any concerns. If the review identifies issues, the agent goes back to Stage 4 to fix them.

### Stage 7: Approval

If the permission system requires approval for this action:

- The agent presents to the user:
  - What it built and why
  - The design document
  - The code (or a summary + diff for core changes)
  - Test results
  - Self-review results
- The user can: approve, request changes, or reject
- If approved, proceed to deployment
- If changes requested, go back to Stage 4 with the feedback
- If rejected, log the rejection and clean up temporary files

If full auto mode is enabled, this stage is skipped (but still logged).

### Stage 8: Deployment

**For plugins:**
1. Copy the plugin directory from temporary workspace to `/plugins/<name>/`
2. Add entry to `tools/manifest.json`
3. Hot-reload the tool registry (no agent restart needed)
4. Create a git commit with the new plugin

**For core modifications:**
1. Create a git commit with the current state (pre-change snapshot)
2. Apply the changes to the actual source files
3. Run the full test suite one final time against the real files
4. If tests pass: create a commit with the changes, tag it as a self-modification
5. If tests fail: revert to the pre-change commit, log the failure
6. Restart the affected modules (or the entire agent if the change requires it)

### Stage 9: Documentation

After successful deployment, the agent updates its own documentation:

1. **Plugin README** (`/plugins/<name>/README.md`): What it does, how it works, example usage
2. **Capabilities registry** (`/knowledge/system/capabilities.md`): Add the new capability with description and date
3. **Changelog** (`/knowledge/system/changelog.md`): Log what was added/changed and why
4. **Architecture docs** (if core was modified): Update relevant architecture documentation

This documentation is critical — it's how the agent will understand this capability in future sessions.

### Stage 10: Monitoring

The first N executions (default: 5) of a newly deployed tool are logged with extra detail:

- Full input and output
- Execution time
- Any errors or unexpected behavior
- Resource usage

If the tool fails during this monitoring period, the agent can auto-rollback and flag it for review. After the monitoring period, logging returns to normal levels.

## Pipeline Safeguards

### Budget Limits

Self-development has resource limits to prevent runaway loops:

- **Max LLM calls per development cycle**: 50 (configurable)
- **Max time per development cycle**: 30 minutes (configurable)
- **Max retry attempts per stage**: 3
- **Max concurrent development tasks**: 1 (to prevent conflicts)

If any limit is hit, the pipeline halts, logs the state, and reports to the user.

### Infinite Loop Prevention

The agent tracks development attempts in its memory. If it has tried and failed to build the same capability 3 times, it:

1. Documents the failure pattern in `/knowledge/learned/failures/`
2. Stops trying automatically
3. Reports to the user with its analysis of why it keeps failing
4. Asks for guidance or additional context

### Dependency Management

When a plugin requires external packages:

- Python: `pip install` into a project-local virtual environment
- Node.js: `npm install` into the plugin's directory
- The agent adds dependencies to a `requirements.txt` or `package.json` in the plugin directory
- System-level packages (e.g., `apt install`) always require user approval, even in full auto mode

### Git Integration

Every successful plugin creation and core modification is automatically committed to git:

- Plugin creation: `[self-create-plugin] Add <name>: <description>`, also updates `knowledge/system/capabilities.md` and `knowledge/system/changelog.md`
- Core modification: `[self-modify] <file>: <goal>`, tagged for rollback support

### Rollback

The `self_rollback` tool allows reverting previous self-modifications:

- `self_rollback(action="list")` — shows all revertible commits (those with `[self-modify]` or `[self-create-plugin]` prefixes)
- `self_rollback(action="revert", commit_hash="abc1234")` — reverts the commit and runs the test suite to verify stability
- Also available via CLI: `elophanto rollback`

Core modifications via `self_modify_source` automatically rollback if the test suite fails after applying the change — no manual intervention needed.

### Conflict Resolution

If a new plugin or core change conflicts with existing capabilities:

- The agent detects conflicts during the design phase (by checking the manifest and existing tool names)
- Naming conflicts are resolved by appending a version suffix or using a more specific name
- Behavioral conflicts (two tools that do similar things) are logged, and the agent may deprecate the older tool
