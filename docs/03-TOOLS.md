# EloPhanto — Tool Reference

## Tool Interface

Every tool — built-in or self-created — must implement this interface:

- **name**: Unique string identifier (snake_case, e.g., `shell_execute`)
- **description**: Clear natural language description. This is what the LLM reads to decide when to use the tool. Quality of this description directly impacts agent effectiveness.
- **input_schema**: JSON Schema object defining parameters, types, required fields, and descriptions.
- **output_schema**: JSON Schema object defining the return format.
- **permission_level**: One of `safe`, `moderate`, `destructive`, `critical`. Determines approval requirements.
- **execute(params) → result**: The implementation. Receives validated input, returns structured output. Must handle errors gracefully and return error information rather than crashing.
- **test file**: Every tool must have an associated test file with unit tests and (where applicable) integration tests.

### Permission Levels

| Level | Description | Ask Always | Smart Auto | Full Auto |
|---|---|---|---|---|
| `safe` | Read-only, no side effects | Ask | Auto | Auto |
| `moderate` | Writes data, creates files | Ask | Ask | Auto |
| `destructive` | Deletes data, sends comms, modifies system | Ask | Ask | Auto |
| `critical` | Irreversible system changes, core modification | Ask | Ask | Ask |

## Built-in Tools

### System Tools

#### `shell_execute`

Runs a shell command on the user's system and returns stdout, stderr, and exit code.

- **Permission**: `destructive` (default). Can be downgraded to `moderate` for specific whitelisted commands via config.
- **Input**: `command` (string), `working_directory` (string, optional), `timeout` (integer, seconds, default 30)
- **Output**: `stdout` (string), `stderr` (string), `exit_code` (integer), `timed_out` (boolean)
- **Safety**: Commands are logged before execution. In Smart Auto mode, read-only commands (`ls`, `cat`, `pwd`, `which`, `echo`, `grep`, `find`, `wc`, `head`, `tail`, `df`, `du`, `ps`, `uname`) auto-approve. Write commands require approval. Hard blacklist patterns always require approval regardless of mode: `rm -rf /`, `mkfs`, `dd if=`, `:(){ :|:& };:`, `> /dev/sda`, `chmod -R 777 /`, `DROP DATABASE`, `TRUNCATE`.

#### `file_read`

Reads the contents of a file. Supports text files directly and binary files as base64.

- **Permission**: `safe`
- **Input**: `path` (string), `encoding` (string, default `utf-8`), `lines` (object with `start` and `end`, optional — for reading specific line ranges)
- **Output**: `content` (string), `size_bytes` (integer), `mime_type` (string), `line_count` (integer)

#### `file_write`

Creates or overwrites a file with given content.

- **Permission**: `moderate`
- **Input**: `path` (string), `content` (string), `create_directories` (boolean, default true), `backup` (boolean, default true — creates `.bak` before overwrite)
- **Output**: `path` (string), `size_bytes` (integer), `backed_up` (boolean)

#### `file_list`

Lists files and directories at a given path with optional filtering.

- **Permission**: `safe`
- **Input**: `path` (string), `recursive` (boolean, default false), `pattern` (string, glob pattern, optional), `include_hidden` (boolean, default false)
- **Output**: `entries` (array of objects with `name`, `path`, `type`, `size_bytes`, `modified_at`)

#### `vault_set`

Stores a credential in the encrypted vault.

- **Permission**: `critical`
- **Input**: `key` (string — e.g., 'telegram_bot_token', 'github.com'), `value` (string — the credential to store)
- **Output**: `key` (string), `stored` (boolean)
- **Note**: Requires the vault to be unlocked. The agent should use this tool instead of running vault CLI commands via shell_execute.

#### `file_delete`

Deletes a file or directory.

- **Permission**: `destructive`
- **Input**: `path` (string), `recursive` (boolean, default false for safety)
- **Output**: `deleted` (boolean), `path` (string)

#### `file_move`

Moves or renames a file or directory.

- **Permission**: `moderate`
- **Input**: `source` (string), `destination` (string)
- **Output**: `source` (string), `destination` (string), `moved` (boolean)

### Browser Tools

#### `browser_connect`

Establishes a WebSocket connection to the EloPhanto Chrome extension running in the user's browser.

- **Permission**: `safe`
- **Input**: `port` (integer, default 7600)
- **Output**: `connected` (boolean), `tabs` (array of open tab summaries), `browser_version` (string)

#### `browser_navigate`

Opens a URL in the user's browser (new tab or existing tab).

- **Permission**: `moderate`
- **Input**: `url` (string), `tab_id` (integer, optional — if omitted, opens new tab), `wait_for` (string, optional — CSS selector to wait for before returning)
- **Output**: `tab_id` (integer), `title` (string), `url` (string), `loaded` (boolean)

#### `browser_read_page`

Reads the current page content — text, HTML structure, or a screenshot.

- **Permission**: `safe`
- **Input**: `tab_id` (integer), `mode` (enum: `text`, `html`, `screenshot`, `accessibility_tree`), `selector` (string, optional — read only a specific element)
- **Output**: varies by mode — `text` returns string, `html` returns string, `screenshot` returns base64 image, `accessibility_tree` returns structured object

#### `browser_interact`

Performs an action in the browser — click, type, scroll, select, submit.

- **Permission**: `destructive` for form submissions and clicks that navigate away. `moderate` for typing and scrolling.
- **Input**: `tab_id` (integer), `action` (enum: `click`, `type`, `scroll`, `select`, `submit`, `hover`, `wait`), `selector` (string, CSS selector for target element), `value` (string, for type/select actions), `timeout` (integer, seconds)
- **Output**: `success` (boolean), `action` (string), `page_changed` (boolean), `new_url` (string, if navigation occurred)

#### `browser_tabs`

Lists, creates, closes, or switches between browser tabs.

- **Permission**: `safe` for list, `moderate` for create/switch, `destructive` for close
- **Input**: `action` (enum: `list`, `create`, `close`, `switch`), `tab_id` (integer, for close/switch), `url` (string, for create)
- **Output**: `tabs` (array), `active_tab` (integer)

#### `browser_cookies`

Reads cookies for a given domain. Used for understanding authentication state.

- **Permission**: `destructive` (cookies contain session tokens)
- **Input**: `domain` (string)
- **Output**: `cookies` (array of name/value/expiry objects)

#### `browser_download`

Downloads a file from the browser.

- **Permission**: `destructive`
- **Input**: `url` (string), `save_path` (string)
- **Output**: `path` (string), `size_bytes` (integer), `mime_type` (string)

#### `browser_screenshot`

Takes a screenshot of the current tab or a specific element.

- **Permission**: `safe`
- **Input**: `tab_id` (integer), `selector` (string, optional), `full_page` (boolean, default false)
- **Output**: `image_base64` (string), `width` (integer), `height` (integer)

### Communication Tools

Note: These are likely to be self-developed by the agent on first need. They are listed here as reference implementations / targets for what the agent should build.

#### `gmail_read`

Reads emails from the user's Gmail account via the Gmail API.

- **Permission**: `moderate`
- **Input**: `query` (string, Gmail search syntax), `max_results` (integer, default 10), `include_body` (boolean, default true)
- **Output**: `messages` (array of objects with `id`, `from`, `to`, `subject`, `date`, `body`, `labels`, `attachments`)

#### `gmail_send`

Sends an email via the user's Gmail account.

- **Permission**: `destructive`
- **Input**: `to` (string or array), `subject` (string), `body` (string), `cc` (array, optional), `bcc` (array, optional), `attachments` (array of file paths, optional), `reply_to_id` (string, optional)
- **Output**: `sent` (boolean), `message_id` (string)

#### `gmail_search`

Searches Gmail using Gmail's search operators.

- **Permission**: `safe`
- **Input**: `query` (string), `max_results` (integer)
- **Output**: `results` (array of message summaries)

### Skills Tools

#### `skill_read`

Reads a skill's SKILL.md content to learn best practices before starting a task.

- **Permission**: `safe`
- **Input**: `skill_name` (string)
- **Output**: `skill_name` (string), `content` (string — full SKILL.md content)

#### `skill_list`

Lists all available skills with their descriptions and trigger keywords.

- **Permission**: `safe`
- **Input**: none
- **Output**: `skills` (array of objects with `name`, `description`, `triggers`, `location`), `count` (integer)

### Knowledge Tools

#### `knowledge_search`

Performs semantic search across the markdown knowledge base using local embeddings.

- **Permission**: `safe`
- **Input**: `query` (string), `scope` (enum: `all`, `system`, `user`, `learned`, `plugins`, default `all`), `max_results` (integer, default 5)
- **Output**: `results` (array of objects with `file`, `section`, `content`, `similarity_score`)

#### `knowledge_write`

Creates or updates a markdown file in the knowledge base.

- **Permission**: `moderate` for `learned/` and `plugins/`. `critical` for `system/`.
- **Input**: `path` (string, relative to `/knowledge/`), `content` (string, markdown), `mode` (enum: `create`, `replace`, `append`)
- **Output**: `path` (string), `action` (string), `indexed` (boolean — whether the file was re-embedded)

#### `knowledge_index`

Triggers re-indexing of the knowledge base (re-chunks and re-embeds markdown files).

- **Permission**: `safe`
- **Input**: `scope` (enum: `all`, `changed_only`), `path` (string, optional — index a specific file)
- **Output**: `files_indexed` (integer), `chunks_created` (integer), `duration_seconds` (number)

### Data Tools

#### `db_query`

Executes a read-only SQL query against the local SQLite database.

- **Permission**: `safe`
- **Input**: `sql` (string), `params` (array, optional — for parameterized queries)
- **Output**: `rows` (array of objects), `columns` (array of strings), `row_count` (integer)
- **Safety**: Only SELECT statements allowed. Any other statement type is rejected.

#### `db_write`

Executes a write SQL statement (INSERT, UPDATE, DELETE, CREATE TABLE) against the local database.

- **Permission**: `moderate` for INSERT/UPDATE. `destructive` for DELETE/DROP.
- **Input**: `sql` (string), `params` (array, optional)
- **Output**: `affected_rows` (integer), `last_insert_id` (integer, if applicable)

#### `llm_call`

Makes an LLM inference call through the router. This is the agent's ability to "think" using a specific model for a specific purpose.

- **Permission**: `safe`
- **Input**: `prompt` (string or array of messages), `model` (string, optional — if omitted, the router selects based on task type), `task_type` (enum: `planning`, `coding`, `analysis`, `simple`, `embedding`), `max_tokens` (integer, optional), `temperature` (number, optional), `system_prompt` (string, optional)
- **Output**: `response` (string), `model_used` (string), `tokens_used` (object with `input` and `output`), `cost_estimate` (number, USD)

### Self-Development Tools

#### `self_read_source`

Reads EloPhanto's own source code files.

- **Permission**: `safe`
- **Input**: `path` (string, relative to project root)
- **Output**: `content` (string), `language` (string), `line_count` (integer)

#### `self_modify_source`

Proposes and applies a modification to EloPhanto's own source code. Goes through the full QA pipeline.

- **Permission**: `critical`
- **Input**: `path` (string), `change_description` (string), `new_content` (string), `reason` (string)
- **Output**: `diff` (string), `tests_passed` (boolean), `test_results` (string), `applied` (boolean), `rollback_commit` (string)

#### `self_create_plugin`

Creates a new plugin following the full self-development pipeline. This is a composite tool that orchestrates the entire process.

- **Permission**: `critical`
- **Input**: `name` (string), `description` (string), `goal` (string — what the plugin should accomplish)
- **Output**: `plugin_path` (string), `tests_passed` (boolean), `registered` (boolean), `documentation` (string — path to generated README)

#### `self_list_capabilities`

Lists all current capabilities (built-in tools + plugins) with their descriptions and status.

- **Permission**: `safe`
- **Input**: `filter` (enum: `all`, `built_in`, `plugins`, `failed`, optional)
- **Output**: `capabilities` (array of objects with `name`, `type`, `description`, `permission_level`, `status`, `created_at`)

#### `self_run_tests`

Runs the test suite — either for a specific plugin, a specific module, or the entire project.

- **Permission**: `safe`
- **Input**: `scope` (enum: `all`, `core`, `plugin`), `target` (string, optional — plugin name or module path)
- **Output**: `passed` (integer), `failed` (integer), `errors` (array of strings), `duration_seconds` (number)

#### `self_rollback`

Reverts a previous self-modification or plugin creation commit.

- **Permission**: `critical`
- **Input**: `action` (enum: `list`, `revert`), `commit_hash` (string, required for `revert`)
- **Output**: For `list`: `commits` (array of revertible commits), `count` (integer). For `revert`: `reverted_commit` (string), `reverted_message` (string), `tests_passed` (boolean)
- **Safety**: Only allows reverting commits tagged with `[self-modify]` or `[self-create-plugin]` prefixes. Runs test suite after rollback.

### Scheduling Tools

#### `schedule_task`

Creates a recurring or one-time scheduled task.

- **Permission**: `moderate`
- **Input**: `name` (string), `task_goal` (string — what to execute), `schedule` (string — see below), `description` (string, optional), `max_retries` (integer, optional)
- **Output**: `schedule_id` (string), `type` (enum: `recurring`, `one_time`), `name` (string), and either `cron_expression` (recurring) or `run_at` (one-time)
- **Schedule formats**:
  - Recurring: cron expression (`0 9 * * *`) or natural language (`every morning at 9am`, `every hour`, `every monday at 2pm`, `every 5 minutes`)
  - One-time: delay-based (`in 5 minutes`, `in 1 hour`, `in 2 days`, `after 30 seconds`) or time-based (`at 3pm`, `at 15:30`)
  - One-time tasks auto-delete after execution

#### `schedule_list`

Lists all scheduled tasks.

- **Permission**: `safe`
- **Input**: `filter` (enum: `all`, `active`, `paused`)
- **Output**: `tasks` (array of task objects with `id`, `name`, `schedule`, `next_run`, `last_run`, `status`)
