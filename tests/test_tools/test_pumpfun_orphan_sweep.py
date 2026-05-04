"""Regression tests for the pumpfun orphan-process sweep.

Production bug: state.json holds at most ONE supervisor PID. If
``start_stream`` was called twice without an intervening ``stop``
(agent crash, double-click, lost state), the older supervisor's PID
was overwritten and stayed alive — happily pushing video to the same
pump.fun WHIP endpoint forever. Real-world hit: 3 zombies from prior
days streaming the same mint at once.

Fix: ``_find_orphans_for_mint`` scans `ps` for any process whose
cmdline references this mint's per-mint state files. ``stop_stream``
and ``start_stream`` both call it before doing their thing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.pumpfun.orchestrator import _find_orphans_for_mint

_MINT = "BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump"


def _spawn_fake_supervisor(state_dir: Path) -> subprocess.Popen:
    """Spawn a long-running process whose cmdline contains the mint
    prefix in a state-file-shaped path.

    We don't spawn a real ffmpeg (no binary required, no network) —
    just `python -c sleep` with an argv crafted to match the
    `_find_orphans_for_mint` filter:
      - the cmdline must include the 16-char mint prefix
      - the cmdline must include `_ffmpeg_supervisor` or start with
        `ffmpeg`
    """
    state_file = state_dir / f"{_MINT[:16]}.config.json"
    state_file.write_text("{}")
    # Tag this process as a fake `_ffmpeg_supervisor` by mentioning
    # it on argv. The real one runs as `python -m
    # tools.pumpfun._ffmpeg_supervisor`; we mimic the substring.
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import time; time.sleep(60)  # _ffmpeg_supervisor stand-in for {state_file}",
        ]
    )


@pytest.fixture
def fake_proc(tmp_path: Path):
    proc = _spawn_fake_supervisor(tmp_path)
    # Give the OS a moment to populate the cmdline in `ps`.
    time.sleep(0.2)
    yield proc
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


class TestOrphanFinder:
    def test_empty_mint_returns_empty(self) -> None:
        assert _find_orphans_for_mint("") == set()

    def test_finds_supervisor_with_matching_mint(self, fake_proc) -> None:
        """A supervisor process whose cmdline contains the mint prefix
        is found, even if state.json doesn't know about it (which is
        the whole point of the sweep)."""
        if not shutil.which("ps"):
            pytest.skip("`ps` not available — sweep returns empty here, no test")
        found = _find_orphans_for_mint(_MINT)
        assert fake_proc.pid in found, (
            f"sweep should have found PID {fake_proc.pid} via mint prefix "
            f"{_MINT[:16]} in its cmdline; got {found}"
        )

    def test_does_not_match_unrelated_processes(self, tmp_path: Path) -> None:
        """A python process that does NOT mention the mint prefix must
        not be matched — the sweep shouldn't kill innocent bystanders."""
        if not shutil.which("ps"):
            pytest.skip("`ps` not available")
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        time.sleep(0.2)
        try:
            found = _find_orphans_for_mint(_MINT)
            assert unrelated.pid not in found
        finally:
            unrelated.terminate()
            try:
                unrelated.wait(timeout=3)
            except subprocess.TimeoutExpired:
                unrelated.kill()
                unrelated.wait()

    def test_does_not_match_different_mint(self, fake_proc) -> None:
        """A supervisor for mint A must not be returned when querying
        for mint B. The mint prefix is the discriminator."""
        if not shutil.which("ps"):
            pytest.skip("`ps` not available")
        other_mint = "FfFfFfFfFfFfFfFfNotARealMintForTesting"
        found = _find_orphans_for_mint(other_mint)
        assert fake_proc.pid not in found

    def test_skips_dead_pids(self, tmp_path: Path) -> None:
        """A process that died after `ps` snapshotted but before
        `_is_alive` was called should not appear in the result.
        Tested by killing the proc immediately and confirming sweep
        doesn't include it (timing-dependent, but the _is_alive
        guard inside the function ensures correctness even when ps
        races us)."""
        if not shutil.which("ps"):
            pytest.skip("`ps` not available")
        proc = _spawn_fake_supervisor(tmp_path)
        time.sleep(0.1)
        proc.terminate()
        proc.wait(timeout=3)
        # Even if `ps` still has the process listed in some buffer,
        # _is_alive(pid) returns False after waitpid reaped it.
        found = _find_orphans_for_mint(_MINT)
        assert proc.pid not in found

    def test_safe_when_ps_missing(self, monkeypatch) -> None:
        """If `ps` is unavailable (sandboxed env, weird container), the
        sweep returns an empty set rather than crashing the stop path.
        Stop should still proceed — better to leak orphans than to
        wedge stop entirely."""
        # Force the `ps` lookup to fail by clobbering subprocess.run
        # with one that raises FileNotFoundError, mimicking a missing
        # binary.
        import tools.pumpfun.orchestrator as orch

        def boom(*args, **kwargs):
            raise FileNotFoundError("no ps in this sandbox")

        monkeypatch.setattr(orch.subprocess, "run", boom)
        # Must not raise.
        assert _find_orphans_for_mint(_MINT) == set()


# ---------------------------------------------------------------------------
# Cleanup safety net: if anything above leaks a sleeping python proc,
# kill it on session teardown so we don't pollute the dev box.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def _reap_session_leaks():
    yield
    # Best-effort sweep at end of module. Match by the unique substring
    # we put in our test argv.
    try:
        proc = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in proc.stdout.splitlines():
            if "_ffmpeg_supervisor stand-in" in line:
                try:
                    pid = int(line.strip().split(None, 1)[0])
                    os.kill(pid, 9)
                except (ValueError, OSError):
                    pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# _resolve_idle_frame — picks operator-supplied idle.{png,jpg,jpeg,webp}
# ---------------------------------------------------------------------------


class TestResolveIdleFrame:
    """Bug we hit in production: orchestrator hardcoded `idle.png`,
    so a user who saved their custom frame as `idle.jpg` got the
    auto-generated green placeholder instead. ffmpeg sniffs the
    actual format from bytes regardless of extension, so accepting
    any of png/jpg/jpeg/webp is the right behaviour."""

    def test_picks_jpg_when_only_jpg_present(self, tmp_path: Path) -> None:
        from tools.pumpfun.orchestrator import _resolve_idle_frame

        (tmp_path / "livestream_videos").mkdir()
        (tmp_path / "livestream_videos" / "idle.jpg").write_bytes(b"\xff\xd8jpg")
        result = _resolve_idle_frame(workspace_dir=tmp_path, mint=_MINT)
        assert result.name == "idle.jpg"
        assert result.is_file()

    def test_png_wins_over_jpg_when_both_present(self, tmp_path: Path) -> None:
        """Order in _IDLE_EXTENSIONS is png first because that's what
        we generate; if the operator has both an old auto-generated
        png AND their own jpg, prefer png. They can delete the png to
        force the jpg path."""
        from tools.pumpfun.orchestrator import _resolve_idle_frame

        (tmp_path / "livestream_videos").mkdir()
        (tmp_path / "livestream_videos" / "idle.jpg").write_bytes(b"\xff\xd8jpg")
        (tmp_path / "livestream_videos" / "idle.png").write_bytes(b"\x89PNGfake")
        result = _resolve_idle_frame(workspace_dir=tmp_path, mint=_MINT)
        assert result.name == "idle.png"

    def test_returns_canonical_png_path_when_nothing_present(
        self, tmp_path: Path
    ) -> None:
        """Caller will _generate_idle_png at this path. Must be the
        .png canonical name so the next call's discovery hits cache."""
        from tools.pumpfun.orchestrator import _resolve_idle_frame

        result = _resolve_idle_frame(workspace_dir=tmp_path, mint=_MINT)
        assert result.name == "idle.png"
        assert result.parent == tmp_path / "livestream_videos"
        # Function creates the parent dir so the generator can write into it.
        assert result.parent.is_dir()

    def test_no_workspace_falls_back_to_state_dir(self) -> None:
        from tools.pumpfun.orchestrator import _resolve_idle_frame

        result = _resolve_idle_frame(workspace_dir=None, mint=_MINT)
        # mint-prefix-suffixed name to keep multiple mints from
        # colliding on the same shared state dir.
        assert _MINT[:16] in result.name
        assert result.name.endswith(".idle.png")
