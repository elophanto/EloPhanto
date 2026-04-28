"""Loop supervisor for ``pump_livestream`` — internal helper.

Spawned as a detached subprocess by ``start_stream(..., loop=True)``.
Restarts the ``lk`` publisher every time it exits (which happens at the
end of each playthrough since the publisher uses ``--exit-after-publish``)
until a stop-marker file appears, at which point it exits cleanly.

Tiny gap (~hundreds of ms) between iterations while ``lk`` reconnects
to the LiveKit room. Acceptable for "stream this video on a loop"
marketing use cases. For truly seamless loops we'd need a FIFO with
ffmpeg ``-stream_loop`` writing into it, which is more fragile.

This file is invoked as ``python -m tools.pumpfun._loop_runner ...``;
it deliberately has no other public surface.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(prog="pumpfun-loop-runner")
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--h264", required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--mint", required=True)
    parser.add_argument(
        "--room", required=True, help="LiveKit room name (from create-livestream JWT)."
    )
    parser.add_argument("--lk-bin", default="lk")
    parser.add_argument(
        "--stop-marker",
        required=True,
        help="Path to a file whose existence ends the loop after the "
        "current playthrough.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=0,
        help="Hard cap on loop iterations (0 = infinite). Belt-and-"
        "suspenders against runaway loops.",
    )
    args = parser.parse_args()

    stop_marker = Path(args.stop_marker)
    iteration = 0

    # Forward SIGTERM/SIGINT to the active lk child cleanly.
    active_proc: subprocess.Popen | None = None  # type: ignore[type-arg]

    def _handle_signal(_signum: int, _frame: object) -> None:
        # Touch the stop marker so the next iteration check exits.
        try:
            stop_marker.touch()
        except OSError:
            pass
        if active_proc is not None and active_proc.poll() is None:
            try:
                active_proc.terminate()
            except OSError:
                pass

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while True:
        if stop_marker.exists():
            try:
                stop_marker.unlink()
            except OSError:
                pass
            print(f"[loop] stop marker found, exiting after {iteration} iters")
            return

        if args.max_iterations and iteration >= args.max_iterations:
            print(f"[loop] hit max-iterations={args.max_iterations}, exiting")
            return

        iteration += 1
        print(f"[loop] iteration {iteration} starting", flush=True)

        cmd = [
            args.lk_bin,
            "room",
            "join",
            "--url",
            args.url,
            "--token",
            args.token,
            "--publish",
            args.h264,
            "--fps",
            str(args.fps),
            "--exit-after-publish",
            args.room,
        ]
        active_proc = subprocess.Popen(  # noqa: S603 — controlled command
            cmd,
            stdout=sys.stdout,
            stderr=sys.stderr,
            close_fds=True,
        )
        try:
            rc = active_proc.wait()
        except KeyboardInterrupt:
            rc = -1
        active_proc = None
        print(f"[loop] iteration {iteration} ended rc={rc}", flush=True)

        # Brief pause to avoid hot-looping if lk is failing fast.
        time.sleep(0.5)


if __name__ == "__main__":
    main()
