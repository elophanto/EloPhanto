"""CLI wrapper around ``tools.pumpfun.orchestrator``.

The native ``pump_livestream`` tool is the chat-callable version; this
script is the same logic exposed for shell debugging. ``VAULT_PASSWORD``
must be set in the env so it can decrypt the agent's wallet.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make the project root importable
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _unlock_vault():  # type: ignore[no-untyped-def]
    from core.config import load_config
    from core.vault import Vault

    password = os.environ.get("VAULT_PASSWORD")
    if not password:
        raise RuntimeError(
            "VAULT_PASSWORD env var required. Or invoke via the "
            "pump_livestream native tool from chat instead."
        )
    config = load_config()
    return Vault.unlock(config.project_root, password)


def main() -> None:
    parser = argparse.ArgumentParser(prog="pump_livestream")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Register a stream record on pump.fun")
    p_create.add_argument("mint")

    p_token = sub.add_parser("token", help="Fetch a LiveKit host token for the stream")
    p_token.add_argument("mint")

    p_transcode = sub.add_parser(
        "transcode", help="Convert local video to .h264 (no streaming)"
    )
    p_transcode.add_argument("input")
    p_transcode.add_argument("output")

    p_start = sub.add_parser(
        "start",
        help="End-to-end: ensure stream exists, transcode, publish to LiveKit",
    )
    p_start.add_argument("mint")
    p_start.add_argument("video")
    p_start.add_argument("--fps", type=float, default=30.0)
    p_start.add_argument("--livekit-url", default="")
    p_start.add_argument(
        "--skip-create",
        action="store_true",
        help="Skip POST /create-livestream (use when stream already exists)",
    )
    p_start.add_argument(
        "--keep-h264",
        action="store_true",
        help="Keep the transcoded .h264 file after stopping",
    )

    p_stop = sub.add_parser("stop", help="Stop a running publisher")
    p_stop.add_argument("mint")

    p_status = sub.add_parser("status", help="Report publisher state")
    p_status.add_argument("mint")

    args = parser.parse_args()

    from tools.pumpfun.orchestrator import LivestreamOrchestrator

    vault = _unlock_vault()
    orch = LivestreamOrchestrator(vault)

    if args.cmd == "create":
        out = orch.create_livestream(args.mint)
    elif args.cmd == "token":
        out = orch.get_host_token(args.mint)
    elif args.cmd == "transcode":
        orch.transcode_to_h264(args.input, args.output)
        out = {"status": "ok", "input": args.input, "output": args.output}
    elif args.cmd == "start":
        out = orch.start_stream(
            args.mint,
            args.video,
            fps=args.fps,
            livekit_url=args.livekit_url,
            skip_create=args.skip_create,
            keep_h264=args.keep_h264,
        )
    elif args.cmd == "stop":
        out = orch.stop_stream(args.mint)
    elif args.cmd == "status":
        out = orch.status_stream(args.mint)
    else:
        parser.error("unknown command")
        return

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
