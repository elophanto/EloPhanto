"""Prepare the optional Society bundle for ./start.sh, without changing CLI mode."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def runtime_config_path(arguments: list[str]) -> Path | None:
    """Return the runtime command's config; utility commands never build the UI."""
    if any(argument in {"--help", "-h", "--version"} for argument in arguments):
        return None
    if arguments and arguments[0] not in {"chat", "gateway", "--web"}:
        return None
    path = Path(os.environ.get("ELOPHANTO_CONFIG") or "config.yaml")
    for index, argument in enumerate(arguments):
        if argument == "--config" and index + 1 < len(arguments):
            path = Path(arguments[index + 1])
        elif argument.startswith("--config="):
            path = Path(argument.split("=", 1)[1])
    return path


def source_fingerprint(web: Path) -> str:
    """Content fingerprint avoids rebuilds on every CLI start and catches updates."""
    paths = [web / name for name in ("package.json", "package-lock.json", "index.html")]
    for directory in (web / "src", web / "public"):
        if directory.exists():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    paths.extend(web.glob("*config*"))
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        if path.is_file():
            digest.update(str(path.relative_to(web)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def prepare_society(arguments: list[str], project_root: Path | None = None) -> bool:
    """Build only when enabled and stale; callers continue even on failure."""
    config = runtime_config_path(arguments)
    if config is None:
        return True
    root = (project_root or Path(__file__).resolve().parent.parent).resolve()
    if not config.is_absolute():
        config = root / config
    try:
        from core.config import load_config

        profile = ""
        for index, argument in enumerate(arguments):
            if argument == "--profile" and index + 1 < len(arguments):
                profile = arguments[index + 1]
            elif argument.startswith("--profile="):
                profile = argument.split("=", 1)[1]
        if not load_config(config, profile=profile).society.enabled:
            return True
        web = root / "web"
        signature = source_fingerprint(web)
        stamp = web / "dist" / ".society-build.json"
        if stamp.exists() and (web / "dist" / "index.html").is_file():
            try:
                if json.loads(stamp.read_text()).get("source") == signature:
                    return True
            except (ValueError, OSError):
                pass
        npm = shutil.which("npm")
        if not npm or not shutil.which("node"):
            print("Society needs Node.js and npm to build its graphics. CLI startup will continue.")
            return False
        print("Preparing Agent Society graphics…", flush=True)
        commands = []
        if (
            not (web / "node_modules" / "three" / "package.json").exists()
            or not (web / "node_modules" / "vite" / "bin" / "vite.js").exists()
        ):
            commands.append([npm, "ci"])
        commands.append([npm, "run", "build"])
        for command in commands:
            result = subprocess.run(command, cwd=web, capture_output=True, text=True, timeout=300)
            if result.returncode:
                print("Society build did not complete. CLI startup will continue.")
                print((result.stdout + result.stderr)[-5000:])
                return False
        stamp.write_text(json.dumps({"source": signature}) + "\n")
        print("Agent Society graphics ready.", flush=True)
        return True
    except FileNotFoundError:
        # Let the CLI own missing config diagnostics.
        return True
    except Exception as exc:
        print(f"Society preparation skipped ({type(exc).__name__}). CLI startup will continue.")
        return False


if __name__ == "__main__":
    prepare_society(sys.argv[1:])
