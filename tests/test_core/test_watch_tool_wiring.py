"""Every watch tool must DECLARE the dependencies it uses.

The Agent injects a dependency only where the attribute already exists
(`hasattr(tool, "_vault")`), so a tool that reads `self._vault` without
declaring it in __init__ is silently never wired — and then crashes on
the exact path that needed it. That is what happened to
watch_catalog_collect on 2026-08-27: its open-web research died with
"object has no attribute '_vault'", and the agent fell back to signing in
to fifteen sites, which is precisely what the research path exists to
avoid.

This test reads each tool's own source for `self._x` accesses and asserts
the attribute exists on a freshly built instance.
"""

from __future__ import annotations

import inspect
import re

from tools.watch.tools import create_watch_tools

# Attributes tools define for themselves at runtime, not injected.
_LOCAL = {"_guard", "_watch_manager"}
_SELF_ATTR = re.compile(r"self\.(_[a-z][a-z0-9_]*)")


def test_every_watch_tool_declares_what_it_uses() -> None:
    missing: list[str] = []
    for tool in create_watch_tools():
        try:
            source = inspect.getsource(type(tool))
        except OSError:  # pragma: no cover
            continue
        used = {m for m in _SELF_ATTR.findall(source) if m not in _LOCAL}
        for attr in sorted(used):
            if attr.endswith("(") or callable(getattr(type(tool), attr, None)):
                continue
            if not hasattr(tool, attr):
                missing.append(f"{tool.name} uses self.{attr} but never declares it")
    assert not missing, "; ".join(missing)


def test_the_tools_the_agent_wires_all_exist() -> None:
    """Every name in Agent's watch dependency block must be a real tool —
    a typo there is a tool that silently never gets its manager."""
    import inspect as _inspect

    from core import agent as agent_mod

    source = _inspect.getsource(agent_mod.Agent)
    block = source[source.index('"watch_subject",') : source.index('"watch_catalog",') + 40]
    named = set(re.findall(r'"(watch_[a-z_]+)"', block))
    real = {t.name for t in create_watch_tools()}
    assert named <= real, f"Agent wires tools that do not exist: {sorted(named - real)}"
    # and every tool that needs the manager is in the block
    assert real - named == set(), f"tools never wired by Agent: {sorted(real - named)}"


def test_every_tool_that_declares_a_vault_is_in_the_vault_injection_list() -> None:
    """The manager block and the vault block are separate lists in Agent;
    watch_catalog_collect was in the first and missing from the second, so
    it was built, wired for the register, and still had no vault."""
    import inspect as _inspect

    from core import agent as agent_mod

    source = _inspect.getsource(agent_mod.Agent._inject_vault_deps)
    wired = set(re.findall(r'"(watch_[a-z_]+)"', source))
    needs = {t.name for t in create_watch_tools() if hasattr(t, "_vault")}
    assert needs <= wired, f"declare a vault but never receive one: {sorted(needs - wired)}"


class TestOutputsLandInTheWorkspace:
    """Operator's rule (2026-09-02): every file a watch tool writes lands
    under config.yaml's agent.workspace — never ~/Desktop."""

    def test_default_output_is_under_the_workspace(self, tmp_path) -> None:
        from tools.watch.tools import _workspace_out

        class Cfg:
            workspace = str(tmp_path / "ws")

        out = _workspace_out(Cfg(), "competitor-deck.pptx")
        assert out == tmp_path / "ws" / "watch" / "competitor-deck.pptx"
        assert out.parent.is_dir()                                   # created, ready to write
        assert _workspace_out(Cfg()) == tmp_path / "ws" / "watch"
        assert str(_workspace_out(None, "x.xlsx")).startswith("workspace/")   # no config: still not the home dir

    def test_no_watch_tool_advertises_the_desktop(self) -> None:
        import json

        from tools.watch import tools as T

        for name in dir(T):
            cls = getattr(T, name)
            if isinstance(cls, type) and name.startswith("Watch") and name.endswith("Tool"):
                try:
                    schema = json.dumps(cls().input_schema)
                except Exception:
                    continue
                assert "Desktop" not in schema, name


def test_the_agent_hands_itself_to_the_tools_that_delegate_browser_work() -> None:
    """docs/90: watch_login and the registered read hand the browser work
    to the agent (run_isolated). Without the injection they silently fall
    back to the script — so the injection is pinned like the vault's."""
    import inspect as _inspect

    from core import agent as agent_mod

    source = _inspect.getsource(agent_mod.Agent._inject_company_deps)
    watch_block = source[source.index('"watch_login"'):]
    assert 'if hasattr(tool, "_agent"):' in watch_block and "tool._agent = self" in watch_block
    needs = {t.name for t in create_watch_tools() if hasattr(t, "_agent")}
    assert {"watch_login", "watch_catalog_collect"} <= needs
    wired = set(re.findall(r'"(watch_[a-z_]+)"', source))
    assert needs <= wired, f"declare an agent but never receive one: {sorted(needs - wired)}"
