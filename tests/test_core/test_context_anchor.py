"""2026-09-04: the user asked why an export saved with the wrong extension;
the agent rebuilt a scorecard from two days earlier.

A recursive grep over a project's built bundles returned megabytes, the
context blew past the emergency trim, the trim kept "the first two
messages" — in a session with persisted history, a command from another
day — plus the last five, and the model ran the command it found at the
top. Three fixes, each tested here: tool output is clipped at the source
and at the door, and the emergency trim keeps the current task, never the
oldest messages."""

from __future__ import annotations

import json

import pytest


class TestEmergencyTrimKeepsTheTask:
    def _history(self) -> list[dict]:
        return [
            {
                "role": "user",
                "content": "watch_scorecard format=xlsx providers_from=game_portfolio.csv",
            },
            {"role": "assistant", "content": "Generated the scorecard."},
            {"role": "user", "content": "build it"},
            {"role": "assistant", "content": "Built the engine."},
            {"role": "user", "content": "it doesn't save as zip but some zfo?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "shell_execute", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "x" * 50},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {"name": "file_list", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c2", "content": "y" * 50},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c3",
                        "type": "function",
                        "function": {"name": "shell_execute", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c3", "content": "z" * 50},
        ]

    def test_the_stale_command_is_gone_and_the_question_stays(self) -> None:
        from core.context_compressor import emergency_trim

        out = emergency_trim(self._history(), keep_last=5)
        texts = [m.get("content") for m in out if isinstance(m.get("content"), str)]
        assert not any("watch_scorecard" in t for t in texts)
        assert any("zfo" in t for t in texts)
        assert out[0]["content"].startswith("[context trimmed")
        assert "LAST user message" in out[0]["content"]

    def test_a_leading_system_message_survives(self) -> None:
        from core.context_compressor import emergency_trim

        msgs = [{"role": "system", "content": "you are the agent"}] + self._history()
        out = emergency_trim(msgs, keep_last=3)
        assert out[0]["role"] == "system"
        assert out[1]["content"].startswith("[context trimmed")
        assert any("zfo" in str(m.get("content")) for m in out)

    def test_page_dumps_are_not_goals(self) -> None:
        from core.context_compressor import emergency_trim, is_goal_message

        assert is_goal_message({"role": "user", "content": "fix the export"})
        assert not is_goal_message(
            {"role": "user", "content": "Page after browser_navigate:\n[0] link"}
        )
        assert not is_goal_message({"role": "tool", "content": "fix the export"})
        msgs = [
            {"role": "user", "content": "fix the export"},
            {"role": "assistant", "content": "looking"},
            {"role": "user", "content": "Page after browser_navigate:\n" + "e" * 100},
            {"role": "assistant", "content": "saw it"},
        ] * 3
        out = emergency_trim(msgs, keep_last=2)
        goals = [
            m
            for m in out
            if m.get("role") == "user" and m["content"] == "fix the export"
        ]
        assert goals, "the real request is anchored even when page dumps come after it"

    def test_no_orphaned_tool_results_after_the_cut(self) -> None:
        from core.context_compressor import emergency_trim

        out = emergency_trim(self._history(), keep_last=2)
        call_ids = {
            tc["id"] for m in out if m.get("tool_calls") for tc in m["tool_calls"]
        }
        for m in out:
            if m.get("role") == "tool":
                assert m["tool_call_id"] in call_ids

    @pytest.mark.asyncio
    async def test_tier_three_uses_the_anchor(self) -> None:
        """End to end through tiered_compress with a tiny window and a
        router that cannot summarise: Tier 3 must not resurrect the
        first message."""
        from core.context_compressor import tiered_compress

        class _NoRouter:
            async def complete(self, **kw):
                raise RuntimeError("no model")

        msgs = self._history()
        msgs[6]["content"] = "x" * 4000  # the fat tool result
        out = await tiered_compress(msgs, _NoRouter(), context_window=600)
        texts = " ".join(str(m.get("content")) for m in out)
        assert "watch_scorecard" not in texts
        assert "zfo" in texts


class TestToolOutputIsClippedAtTheSource:
    def test_shell_clip_keeps_head_and_tail_and_says_so(self) -> None:
        from tools.system.shell import clip_output

        text = "A" * 100 + "B" * 100_000 + "C" * 100
        clipped, dropped = clip_output(text, 1_000)
        assert dropped == len(text) - 1_000
        assert clipped.startswith("A" * 100) and clipped.endswith("C" * 100)
        assert "clipped from the middle" in clipped
        assert clip_output("short", 1_000) == ("short", 0)

    @pytest.mark.asyncio
    async def test_shell_tool_reports_the_clip(self, monkeypatch, test_config) -> None:
        import tools.system.shell as sh

        monkeypatch.setattr(sh, "MAX_STDOUT_CHARS", 500)
        t = sh.ShellExecuteTool(test_config)
        res = await t.execute(
            {"command": "python3 -c \"print('x' * 5000)\"", "timeout": 20}
        )
        assert res.success, res.error
        assert len(res.data["stdout"]) < 700
        assert (
            "output_clipped" in res.data
            and "narrow the command" in res.data["output_clipped"]
        )

    @pytest.mark.asyncio
    async def test_file_list_skips_dependency_trees_and_caps(
        self, tmp_path, monkeypatch
    ) -> None:
        import tools.system.filesystem as fs

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.js").write_text("a")
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        for i in range(30):
            (tmp_path / "node_modules" / "pkg" / f"{i}.js").write_text("x")
        t = fs.FileListTool()
        res = await t.execute({"path": str(tmp_path), "recursive": True})
        assert res.success, res.error
        paths = [e["path"] for e in res.data["entries"]]
        assert any(p.endswith("src/a.js") for p in paths)
        assert not any("node_modules/pkg/" in p for p in paths)
        assert "node_modules" in res.data["skipped_dirs"]
        assert any(
            p.endswith("node_modules") for p in paths
        )  # the directory itself is listed, not walked

        monkeypatch.setattr(fs, "MAX_LIST_ENTRIES", 1)
        res = await t.execute({"path": str(tmp_path), "recursive": True})
        assert res.data["count"] == 1 and res.data["truncated"] >= 1
        assert "more entries not shown" in res.data["note"]

        direct = await t.execute(
            {"path": str(tmp_path / "node_modules" / "pkg"), "recursive": False}
        )
        assert direct.data["count"] == 1  # capped at 1 by the monkeypatch, but listed


class TestTheDoorClip:
    def test_a_huge_result_becomes_a_partial_json_envelope(self) -> None:
        from core.agent import _MAX_TOOL_RESULT_CHARS, _clip_tool_content

        small = json.dumps({"ok": True})
        assert _clip_tool_content(small, 1_000) == small
        big = json.dumps({"stdout": "q" * 50_000})
        out = json.loads(_clip_tool_content(big, 2_000))
        assert out["result_clipped"] is True and out["chars_dropped"] > 40_000
        assert "[clipped]" in out["content"] and len(out["content"]) < 2_200
        assert _MAX_TOOL_RESULT_CHARS >= 50_000
