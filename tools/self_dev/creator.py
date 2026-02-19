"""Self-create plugin tool — orchestrates the full plugin creation pipeline."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult
from tools.self_dev.pipeline import (
    check_name_available,
    get_timestamp,
    render_template,
    sanitize_plugin_name,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt for all self-development LLM calls
# ---------------------------------------------------------------------------

_SELF_DEV_SYSTEM = """\
<context>
You are the self-development subsystem of EloPhanto, an autonomous AI agent.
You are creating a new plugin (tool) that will be loaded into the agent's
tool registry at runtime.

<architecture>
- Plugins live in the plugins/ directory, each in its own subdirectory.
- Every plugin has a plugin.py file containing a single tool class.
- Tool classes inherit from BaseTool (from tools.base import BaseTool,
  PermissionLevel, ToolResult).
- Required interface:
  - name property -> str (snake_case tool name)
  - description property -> str (one-line description for the LLM)
  - input_schema property -> dict (JSON Schema for parameters)
  - permission_level property -> PermissionLevel enum
  - async execute(self, params: dict) -> ToolResult
- ToolResult has: success (bool), data (dict, optional), error (str, optional)
- Permission levels: SAFE (read-only), MODERATE (limited writes),
  DESTRUCTIVE (significant changes), CRITICAL (system-level operations)
</architecture>

<conventions>
- Use async/await for all I/O operations.
- Handle errors gracefully — return ToolResult(success=False, error=...) rather
  than raising exceptions from execute().
- Keep dependencies minimal. Prefer stdlib when possible.
- Include type hints on all function signatures.
- Write clear, self-documenting code. Avoid unnecessary comments.
</conventions>
</context>"""


@dataclass
class DevelopmentBudget:
    """Tracks resource usage during a development cycle."""

    max_llm_calls: int = 50
    max_time_seconds: int = 1800
    max_retries: int = 3
    llm_calls_used: int = 0
    start_time: float = 0.0

    def check(self) -> tuple[bool, str]:
        """Returns (within_budget, reason_if_not)."""
        if self.llm_calls_used >= self.max_llm_calls:
            return False, f"LLM call limit reached ({self.max_llm_calls})"
        elapsed = time.monotonic() - self.start_time
        if elapsed > self.max_time_seconds:
            return False, f"Time limit reached ({self.max_time_seconds}s)"
        return True, ""

    def use_call(self) -> None:
        self.llm_calls_used += 1


class SelfCreatePluginTool(BaseTool):
    """Orchestrates the full plugin creation pipeline."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._router: Any = None  # Injected by agent
        self._registry: Any = None  # Injected by agent
        self._plugin_loader: Any = None  # Injected by agent
        self._db: Any = None  # Injected by agent

    @property
    def name(self) -> str:
        return "self_create_plugin"

    @property
    def description(self) -> str:
        return (
            "Create a new plugin/tool through the full development pipeline: "
            "research existing tools, design the plugin, implement it using the "
            "template, write tests, run tests, self-review code, deploy to "
            "plugins/, and document. This is an expensive operation."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "What the new tool should do (natural language)",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Desired snake_case name (optional)",
                },
                "permission_level": {
                    "type": "string",
                    "enum": ["safe", "moderate", "destructive", "critical"],
                    "description": "Permission level (default: moderate)",
                },
            },
            "required": ["goal"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.CRITICAL

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._router:
            return ToolResult(success=False, error="Router not available")

        goal = params["goal"]
        tool_name = params.get("tool_name") or sanitize_plugin_name(goal)
        perm_level = params.get("permission_level", "moderate")

        budget = DevelopmentBudget(start_time=time.monotonic())

        # Check name availability
        if self._registry and not check_name_available(tool_name, self._registry):
            return ToolResult(
                success=False,
                error=f"Tool name '{tool_name}' already exists",
            )

        plugin_dir = self._project_root / "plugins" / tool_name
        template_dir = self._project_root / "plugins" / "_template"

        try:
            # Stage 1: Research
            within, reason = budget.check()
            if not within:
                return ToolResult(success=False, error=f"Budget exceeded: {reason}")

            research = await self._research(goal, budget)

            # Stage 2: Design
            within, reason = budget.check()
            if not within:
                return ToolResult(success=False, error=f"Budget exceeded: {reason}")

            design = await self._design(goal, tool_name, perm_level, research, budget)

            # Stage 3: Implement (render template + generate code)
            within, reason = budget.check()
            if not within:
                return ToolResult(success=False, error=f"Budget exceeded: {reason}")

            class_name = (
                "".join(word.capitalize() for word in tool_name.split("_")) + "Tool"
            )

            context = {
                "plugin_name": tool_name.replace("_", " ").title(),
                "tool_name": tool_name,
                "description": design.get("description", goal),
                "ClassName": class_name,
                "PERMISSION_LEVEL": perm_level.upper(),
                "plugin_dir": tool_name,
                "date": get_timestamp(),
            }

            if template_dir.exists():
                await render_template(template_dir, plugin_dir, context)

            # Generate implementation via LLM
            impl_code = await self._implement(design, tool_name, class_name, budget)

            # Write the generated code
            (plugin_dir / "plugin.py").write_text(impl_code["plugin"], encoding="utf-8")
            (plugin_dir / "test_plugin.py").write_text(
                impl_code["test"], encoding="utf-8"
            )

            # Write schema.json
            schema = {
                "name": tool_name,
                "description": design.get("description", goal),
                "version": "0.1.0",
                "author": "EloPhanto",
                "class_name": class_name,
                "permission_level": perm_level,
                "dependencies": design.get("dependencies", []),
                "created_at": get_timestamp(),
            }
            (plugin_dir / "schema.json").write_text(
                json.dumps(schema, indent=2), encoding="utf-8"
            )

            # Stage 4: Test
            test_result = await self._test(tool_name, plugin_dir, budget)
            if not test_result["passed"]:
                # Try to fix up to max_retries times
                for _attempt in range(budget.max_retries):
                    within, reason = budget.check()
                    if not within:
                        break
                    impl_code = await self._fix(
                        impl_code, test_result["output"], design, budget
                    )
                    (plugin_dir / "plugin.py").write_text(
                        impl_code["plugin"], encoding="utf-8"
                    )
                    test_result = await self._test(tool_name, plugin_dir, budget)
                    if test_result["passed"]:
                        break

                if not test_result["passed"]:
                    return ToolResult(
                        success=False,
                        data={"test_output": test_result["output"]},
                        error=f"Tests failed after {budget.max_retries} retries",
                    )

            # Stage 5: Review
            within, reason = budget.check()
            if within:
                review = await self._review(impl_code["plugin"], design, budget)
                if not review.get("approved", True):
                    logger.warning(
                        f"Self-review flagged issues: {review.get('issues')}"
                    )

            # Stage 6: Deploy — reload plugin into registry
            if self._plugin_loader:
                result = self._plugin_loader.reload_plugin(tool_name)
                if not result.success:
                    # Try fresh load
                    from core.plugin_loader import PluginManifestEntry

                    entry = PluginManifestEntry(
                        name=tool_name,
                        description=design.get("description", goal),
                        version="0.1.0",
                        module_path=f"plugins.{tool_name}.plugin",
                        class_name=class_name,
                        permission_level=perm_level,
                        plugin_dir=plugin_dir,
                    )
                    result = self._plugin_loader.load_plugin(entry)

                if result.success and result.tool and self._registry:
                    self._registry.register(result.tool)

            # Stage 7: Git commit + documentation
            await self._git_commit_and_document(
                tool_name, design.get("description", goal), plugin_dir
            )

            logger.info(f"Plugin '{tool_name}' created and deployed successfully")
            return ToolResult(
                success=True,
                data={
                    "plugin_name": tool_name,
                    "plugin_dir": str(plugin_dir),
                    "class_name": class_name,
                    "tests_passed": True,
                    "llm_calls_used": budget.llm_calls_used,
                },
            )

        except Exception as e:
            logger.error(f"Plugin creation failed: {e}")
            return ToolResult(success=False, error=f"Plugin creation failed: {e}")

    async def _research(self, goal: str, budget: DevelopmentBudget) -> str:
        """Research phase: gather context about similar tools."""
        budget.use_call()
        prompt = (
            f'<task stage="research">\n'
            f"<goal>{goal}</goal>\n\n"
            f"<instructions>\n"
            f"Analyze this tool request and produce a research summary covering:\n"
            f"1. Key functional requirements the tool must satisfy\n"
            f"2. Python libraries that would be useful (prefer well-maintained,\n"
            f"   widely-used packages)\n"
            f"3. Potential edge cases or failure modes to consider\n"
            f"4. Security considerations for the chosen permission level\n\n"
            f"Be concise — this feeds into the design phase.\n"
            f"</instructions>\n"
            f"</task>"
        )
        response = await self._router.complete(
            messages=[
                {"role": "system", "content": _SELF_DEV_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="analysis",
            temperature=0.3,
        )
        return response.content or ""

    async def _design(
        self,
        goal: str,
        tool_name: str,
        perm_level: str,
        research: str,
        budget: DevelopmentBudget,
    ) -> dict[str, Any]:
        """Design phase: create a design document."""
        budget.use_call()
        prompt = (
            f'<task stage="design">\n'
            f"<goal>{goal}</goal>\n"
            f"<tool_name>{tool_name}</tool_name>\n"
            f"<permission_level>{perm_level}</permission_level>\n\n"
            f"<research_context>\n{research}\n</research_context>\n\n"
            f"<instructions>\n"
            f"Design the tool by producing a JSON object with these fields:\n\n"
            f'- "description": One-line description that will be shown to the\n'
            f"  LLM when selecting tools. Make it clear and actionable.\n"
            f'- "parameters": Array of objects, each with: name (str), type\n'
            f"  (JSON Schema type), required (bool), description (str).\n"
            f'- "dependencies": Array of pip package names needed (empty if\n'
            f"  stdlib-only).\n"
            f'- "approach": Implementation strategy in 2-3 sentences.\n'
            f'- "test_plan": Array of test case descriptions to write.\n\n'
            f"Return ONLY the JSON object, no other text.\n"
            f"</instructions>\n"
            f"</task>"
        )
        response = await self._router.complete(
            messages=[
                {"role": "system", "content": _SELF_DEV_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="coding",
            temperature=0.2,
        )
        try:
            # Try to extract JSON from the response
            content = response.content or "{}"
            # Find JSON object in response
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except json.JSONDecodeError:
            pass
        return {
            "description": goal,
            "parameters": [],
            "dependencies": [],
            "approach": "",
        }

    async def _implement(
        self,
        design: dict[str, Any],
        tool_name: str,
        class_name: str,
        budget: DevelopmentBudget,
    ) -> dict[str, str]:
        """Implementation phase: generate plugin code and tests."""
        budget.use_call()
        design_json = json.dumps(design, indent=2)
        prompt = (
            f'<task stage="implement">\n'
            f"<tool_name>{tool_name}</tool_name>\n"
            f"<class_name>{class_name}</class_name>\n\n"
            f"<design>\n{design_json}\n</design>\n\n"
            f"<instructions>\n"
            f"Write the COMPLETE plugin.py file for this tool.\n\n"
            f"<requirements>\n"
            f"- Import from tools.base: BaseTool, PermissionLevel, ToolResult\n"
            f"- Class {class_name} inherits from BaseTool\n"
            f"- Implement all required properties: name (returns '{tool_name}'),\n"
            f"  description, input_schema (JSON Schema dict), permission_level\n"
            f"- Implement: async execute(self, params: dict[str, Any]) -> ToolResult\n"
            f"- Handle errors gracefully — return ToolResult(success=False, error=...)\n"
            f"  instead of raising exceptions\n"
            f"- Use type hints throughout\n"
            f"</requirements>\n\n"
            f"Return the complete file contents starting with imports.\n"
            f"</instructions>\n"
            f"</task>"
        )
        response = await self._router.complete(
            messages=[
                {"role": "system", "content": _SELF_DEV_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="coding",
            temperature=0.2,
        )
        plugin_code = _extract_code(response.content or "")

        budget.use_call()
        test_prompt = (
            f'<task stage="test_generation">\n'
            f"<plugin_code>\n```python\n{plugin_code}\n```\n</plugin_code>\n\n"
            f"<instructions>\n"
            f"Write pytest tests for this EloPhanto plugin.\n\n"
            f"<requirements>\n"
            f"- Import: from plugins.{tool_name}.plugin import {class_name}\n"
            f"- Test the interface: name, description, input_schema structure\n"
            f"- Test execute() with valid parameters (happy path)\n"
            f"- Test execute() with invalid/missing parameters (error cases)\n"
            f"- Use pytest-asyncio for async test functions\n"
            f"- Use @pytest.mark.asyncio decorator on async tests\n"
            f"</requirements>\n\n"
            f"Return the complete test file contents.\n"
            f"</instructions>\n"
            f"</task>"
        )
        test_response = await self._router.complete(
            messages=[
                {"role": "system", "content": _SELF_DEV_SYSTEM},
                {"role": "user", "content": test_prompt},
            ],
            task_type="coding",
            temperature=0.2,
        )
        test_code = _extract_code(test_response.content or "")

        return {"plugin": plugin_code, "test": test_code}

    async def _test(
        self,
        tool_name: str,
        plugin_dir: Path,
        budget: DevelopmentBudget,
    ) -> dict[str, Any]:
        """Test phase: run the plugin's tests."""
        import asyncio

        test_file = plugin_dir / "test_plugin.py"
        if not test_file.exists():
            return {"passed": False, "output": "Test file not found"}

        proc = await asyncio.create_subprocess_exec(
            "python",
            "-m",
            "pytest",
            str(test_file),
            "-v",
            "--tb=short",
            cwd=str(self._project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"passed": False, "output": "Tests timed out"}

        output = stdout.decode("utf-8", errors="replace")
        return {"passed": proc.returncode == 0, "output": output}

    async def _fix(
        self,
        impl_code: dict[str, str],
        test_output: str,
        design: dict[str, Any],
        budget: DevelopmentBudget,
    ) -> dict[str, str]:
        """Fix implementation based on test failures."""
        budget.use_call()
        truncated_output = test_output[-2000:]
        prompt = (
            f'<task stage="fix">\n'
            f"<current_code>\n```python\n{impl_code['plugin']}\n```\n</current_code>\n\n"
            f"<test_output>\n{truncated_output}\n</test_output>\n\n"
            f"<instructions>\n"
            f"The plugin code above failed its tests. Analyze the test output,\n"
            f"identify the root cause of each failure, and fix the code.\n\n"
            f"<rules>\n"
            f"- Do NOT modify the test file — only fix the plugin code.\n"
            f"- Return the COMPLETE fixed plugin.py file contents.\n"
            f"- Ensure all imports are present and correct.\n"
            f"- Verify the fix addresses the actual failure, not just symptoms.\n"
            f"</rules>\n"
            f"</instructions>\n"
            f"</task>"
        )
        response = await self._router.complete(
            messages=[
                {"role": "system", "content": _SELF_DEV_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="coding",
            temperature=0.2,
        )
        fixed = _extract_code(response.content or "")
        return {"plugin": fixed, "test": impl_code["test"]}

    async def _review(
        self,
        code: str,
        design: dict[str, Any],
        budget: DevelopmentBudget,
    ) -> dict[str, Any]:
        """Self-review phase: check code quality and security."""
        budget.use_call()
        design_json = json.dumps(design, indent=2)
        prompt = (
            f'<task stage="review">\n'
            f"<code>\n```python\n{code}\n```\n</code>\n\n"
            f"<design>\n{design_json}\n</design>\n\n"
            f"<instructions>\n"
            f"Review this plugin code against the design specification.\n\n"
            f"<checklist>\n"
            f"- Security: Does the code sanitize inputs? Could it be exploited?\n"
            f"- Resource management: Are files/connections properly closed?\n"
            f"- Error handling: Does execute() catch exceptions and return\n"
            f"  ToolResult(success=False, error=...) instead of raising?\n"
            f"- Edge cases: Does it handle empty input, missing params, timeouts?\n"
            f"- Code quality: Type hints, clear naming, no dead code?\n"
            f"- Design conformance: Does it match the specified parameters and\n"
            f"  approach from the design document?\n"
            f"</checklist>\n\n"
            f"Return ONLY a JSON object:\n"
            f'{{"approved": true/false, "issues": ["description of each issue"]}}\n'
            f"</instructions>\n"
            f"</task>"
        )
        response = await self._router.complete(
            messages=[
                {"role": "system", "content": _SELF_DEV_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            task_type="analysis",
            temperature=0.2,
        )
        try:
            content = response.content or '{"approved": true}'
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except json.JSONDecodeError:
            pass
        return {"approved": True, "issues": []}

    async def _git_commit_and_document(
        self,
        tool_name: str,
        description: str,
        plugin_dir: Path,
    ) -> None:
        """Git commit the new plugin and update knowledge docs."""
        import asyncio
        from datetime import datetime

        now = datetime.now(UTC).strftime("%Y-%m-%d")

        # Update capabilities.md
        caps_file = self._project_root / "knowledge" / "system" / "capabilities.md"
        if caps_file.exists():
            try:
                content = caps_file.read_text(encoding="utf-8")
                entry = f"\n- **{tool_name}**: {description}\n"
                if tool_name not in content:
                    content += entry
                    caps_file.write_text(content, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to update capabilities.md: {e}")

        # Update changelog.md
        changelog = self._project_root / "knowledge" / "system" / "changelog.md"
        if changelog.exists():
            try:
                content = changelog.read_text(encoding="utf-8")
                entry = f"\n## {now}\n\n- Created plugin `{tool_name}`: {description}\n"
                content += entry
                changelog.write_text(content, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to update changelog.md: {e}")

        # Git commit
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "add",
                str(plugin_dir),
                str(caps_file),
                str(changelog),
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)

            commit_msg = f"[self-create-plugin] Add {tool_name}: {description}"
            proc = await asyncio.create_subprocess_exec(
                "git",
                "commit",
                "-m",
                commit_msg,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            logger.info(f"Git commit: {commit_msg}")
        except Exception as e:
            logger.warning(f"Git commit failed (non-fatal): {e}")


def _extract_code(text: str) -> str:
    """Extract code from LLM response (handles markdown fences)."""
    # Try to find fenced code block
    import re

    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # If no fences, return the whole text (likely just code)
    return text.strip()
