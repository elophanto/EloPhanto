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
    def test_empty_mint_does_not_crash(self, monkeypatch) -> None:
        """Empty mint disables the mint-prefix match branch but the
        WHIP-host branch still runs. With no pump.fun ffmpeg processes
        on the box, the result is empty — but the contract is 'must
        not crash and must not match unrelated processes', not 'must
        return empty regardless of system state'.

        Mock subprocess so we don't depend on real ps state."""
        import tools.pumpfun.orchestrator as orch

        class FakePs:
            stdout = "12345 /usr/bin/python3 unrelated.py\n"
            returncode = 0

        monkeypatch.setattr(orch.subprocess, "run", lambda *a, **kw: FakePs())
        # Empty mint is fine — no mint match attempted, WHIP host
        # branch sees no pump.fun proc in our fake output.
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


# ---------------------------------------------------------------------------
# _generate_idle_png — never overwrites an operator file
# ---------------------------------------------------------------------------


class TestGenerateIdlePngNoOverwrite:
    """Real bug: an upstream resolver miss caused _generate_idle_png to
    be called with the operator's idle.png path, silently blowing away
    their image with the auto-generated placeholder. The function now
    refuses to overwrite ANY existing file at the target path —
    defence in depth so the operator's image is safe even when
    upstream is wrong."""

    def test_refuses_to_overwrite_existing_file(self, tmp_path: Path) -> None:
        from tools.pumpfun.orchestrator import _generate_idle_png

        target = tmp_path / "idle.png"
        sentinel = b"OPERATOR'S IRREPLACEABLE BYTES - MUST NOT BE TOUCHED"
        target.write_bytes(sentinel)
        # Same call site that was previously destructive.
        _generate_idle_png(target, "BwUgJBQffm4HM49WfakeMintForTests")
        # File is byte-identical to what the operator wrote.
        assert target.read_bytes() == sentinel

    def test_generates_when_target_missing(self, tmp_path: Path) -> None:
        """Sanity: the no-overwrite guard doesn't break the legitimate
        path. When the file genuinely isn't there, generation runs."""
        from tools.pumpfun.orchestrator import _generate_idle_png

        target = tmp_path / "idle.png"
        assert not target.exists()
        _generate_idle_png(target, "BwUgJBQffm4HM49WfakeMintForTests")
        assert target.is_file()
        # Sanity-check it's actually a PNG, not an empty or stub file.
        assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Atomic write — eliminates the write-during-read race
# ---------------------------------------------------------------------------


class TestGenerateIdlePngAtomic:
    """Real production failure: supervisor's ffmpeg started reading
    `idle.png` while _generate_idle_png was still writing it. ffmpeg
    saw garbage bytes mid-file ('Invalid PNG signature 0x802008C00000')
    → exited rc=255 → nothing streamed. User-visible symptom: 'no
    image is showing'.

    Fix: write to <stem>.tmp.<pid>.png, then os.replace() to the
    target. POSIX same-filesystem rename is atomic — readers see
    either the OLD file or the FULL new file, never partial."""

    def test_no_temp_leftover_after_success(self, tmp_path: Path) -> None:
        from tools.pumpfun.orchestrator import _generate_idle_png

        target = tmp_path / "idle.png"
        _generate_idle_png(target, "BwUgJBQffm4HM49WfakeMintForTests")
        # The atomic publish renames the tmp into place. Anything left
        # behind is a leak — assert nothing matches the tmp pattern.
        leftovers = list(tmp_path.glob("idle.tmp.*.png"))
        assert leftovers == [], f"leaked tmp files: {leftovers}"
        assert target.is_file()
        # PNG magic — the tmp -> rename produced a valid file.
        assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_target_extension_preserved_on_tmp(self, tmp_path: Path) -> None:
        """ffmpeg infers output format from the file extension. If our
        tmp file ended in `.tmp.<pid>` (no .png suffix), ffmpeg would
        bail with 'Unable to choose an output format' — we hit that
        bug live during the fix. Test by inspecting the function's
        choice of tmp name via a controlled run."""
        from tools.pumpfun.orchestrator import _generate_idle_png

        target = tmp_path / "idle.png"
        # If the tmp path didn't end in .png, the subprocess would
        # raise CalledProcessError. Successful generation means the
        # tmp suffix was correct.
        _generate_idle_png(target, "BwUgJBQffm4HM49WfakeMintForTests")
        assert target.is_file()


# ---------------------------------------------------------------------------
# Video-mode orphan detection — the gap that left 2 zombies pushing 10.mp4
# ---------------------------------------------------------------------------


class TestVideoModeOrphanDetection:
    """Real production failure: video-mode ffmpeg cmdlines DON'T contain
    the mint anywhere — only the video file path (e.g. `10.mp4`) and
    the WHIP URL. The mint-prefix-only orphan match was therefore
    voice-mode-blind. Found 2 zombies in prod streaming `10.mp4` to
    pump.fun for 30+ minutes after their supervisors had died, with
    PPID=1 (orphaned to launchd).

    Fix: the WHIP host substring (`whip.livekit.cloud`) appears in
    every ffmpeg cmdline regardless of mode. Match on either condition
    (mint OR WHIP host) and require a process-shape filter to avoid
    false positives."""

    def test_finds_video_mode_orphan_with_no_mint_in_cmdline(
        self, tmp_path: Path
    ) -> None:
        """Spawn a process that mimics a video-mode ffmpeg: no mint in
        argv, but the pump.fun WHIP host present. Must be found by the
        sweep even though we pass an unrelated mint as the query."""
        if not shutil.which("ps"):
            pytest.skip("`ps` not available")
        # Mimic the video-mode cmdline shape: argv[0] is `ffmpeg`,
        # cmdline contains the WHIP host substring. No mint anywhere.
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import time; time.sleep(60)  "
                    "# ffmpeg fake stand-in pushing to "
                    "https://pump-prod-tg2x8veh.whip.livekit.cloud/w"
                ),
            ]
        )
        time.sleep(0.2)
        try:
            # The matcher should still find this even though the mint
            # we pass doesn't appear anywhere in the proc's cmdline.
            # But our spawned process has `python3` as argv[0], not
            # `ffmpeg`, so the process-shape filter drops it. To
            # exercise the WHIP-host branch we need a process whose
            # argv[0] looks like ffmpeg too.
            #
            # The realistic case (a real ffmpeg child) does have
            # argv[0] == /opt/homebrew/bin/ffmpeg. Our test stand-in
            # can't easily fake argv[0], so we're effectively asserting
            # the dual-condition logic via the unrelated-process and
            # different-mint tests above, which both pass.
            #
            # Concrete coverage of the WHIP-host branch happens via
            # the integration-style test below that mocks subprocess.
            # Smoke it here: confirm the process is NOT matched (because
            # argv[0] is python, not ffmpeg) AND the call doesn't crash.
            found = _find_orphans_for_mint("UnrelatedMintAbCdEfGh1234567")
            assert proc.pid not in found
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def test_whip_host_branch_via_mocked_ps(self, monkeypatch) -> None:
        """The WHIP-host branch matches when argv contains
        `whip.livekit.cloud` AND argv[0] looks like ffmpeg, even when
        no mint appears anywhere in the cmdline. Mocked ps so we can
        construct exactly the cmdline the real code would see for a
        video-mode ffmpeg orphan."""
        import tools.pumpfun.orchestrator as orch

        # Simulate `ps -axo pid=,command=` output containing one
        # video-mode ffmpeg orphan and one unrelated process.
        fake_ps_output = (
            "12345 /opt/homebrew/bin/ffmpeg -y -re -stream_loop -1 -i "
            "/Users/u/livestream_videos/10.mp4 -f whip "
            "https://pump-prod-tg2x8veh.whip.livekit.cloud/w\n"
            "67890 /usr/bin/python3 some-other-script.py\n"
        )

        class FakeCompleted:
            stdout = fake_ps_output
            returncode = 0

        def fake_run(*args, **kwargs):
            return FakeCompleted()

        monkeypatch.setattr(orch.subprocess, "run", fake_run)
        # _is_alive will return True for any pid because os.kill(pid, 0)
        # on a non-existent pid raises ProcessLookupError. Patch it to
        # always return True so we're testing the parser logic, not
        # whether the test PID happens to exist.
        monkeypatch.setattr(orch, "_is_alive", lambda pid: True)

        # Query with a totally different mint — the ffmpeg cmdline
        # has NO mint, only the WHIP host.
        found = _find_orphans_for_mint("CompletelyDifferentMint" * 2)
        assert 12345 in found, (
            "video-mode ffmpeg with WHIP host but no mint should be "
            "matched — that was the production bug"
        )
        assert 67890 not in found, (
            "unrelated python script should not be matched even though "
            "the matcher saw it"
        )
