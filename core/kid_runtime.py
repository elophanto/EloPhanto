"""Container runtime abstraction for kid agents.

Kids run inside containers (Docker / Podman / Colima) with hardened
defaults baked in at this layer. The plan's safety invariants are
enforced *here* — there is no `bind_mounts` parameter on `start()`,
no privileged mode, no docker-socket mount, no override knobs that
weaken isolation. The only way to relax them is to edit this file.

See KID_AGENTS_PLAN.md "Isolation guarantees" for the rationale.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tarfile
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)

# Workspace path inside the container — never a host path. The named
# volume is mounted here.
_WORKSPACE = "/workspace"


class ContainerRuntimeError(RuntimeError):
    """Raised by ContainerRuntime when a runtime operation fails."""


class ContainerRuntime(ABC):
    """Abstract container runtime. Subclasses wrap docker / podman / colima.

    Hardened defaults are not subclass-overridable: `start()` always
    passes the safety flags through to the underlying CLI. Subclasses
    only choose which CLI binary to invoke and how to format args.
    """

    name: str = ""

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if this runtime is installed AND working (e.g. for
        Colima, the VM is running). Cached by KidManager — not called
        per-spawn."""

    @abstractmethod
    async def start(
        self,
        *,
        image: str,
        name: str,
        env: dict[str, str],
        volume_name: str,
        memory_mb: int,
        cpus: float,
        pids_limit: int,
        network_mode: str,
        # Hardening knobs from KidConfig — must default to safe values.
        drop_capabilities: bool = True,
        read_only_rootfs: bool = True,
        no_new_privileges: bool = True,
        run_as_uid: int = 10001,
    ) -> str:
        """Start a hardened container; return its container ID.

        NO `bind_mounts` parameter. NO host paths. The named volume is
        the only writable mount aside from the tmpfs at /tmp.
        """

    @abstractmethod
    async def exec(self, container_id: str, cmd: list[str]) -> tuple[int, str, str]:
        """Execute a command inside the container; return (rc, stdout, stderr)."""

    @abstractmethod
    async def stop(self, container_id: str, timeout: int = 10) -> None:
        """Graceful stop with SIGTERM, fallback to SIGKILL after timeout."""

    @abstractmethod
    async def remove(self, container_id: str) -> None:
        """Remove a stopped container. No-op if it's already gone."""

    @abstractmethod
    async def inspect(self, container_id: str) -> dict[str, Any]:
        """Return raw `docker inspect` output as a dict."""

    @abstractmethod
    async def cp_to_container(
        self, container_id: str, dest_path: str, data: bytes
    ) -> None:
        """Write `data` to a file inside the container.

        `dest_path` MUST be inside /workspace. Implementations reject
        any path outside that prefix; this is the only safe surface for
        parent → kid file exchange.
        """

    @abstractmethod
    async def cp_from_container(
        self, container_id: str, src_path: str, max_bytes: int
    ) -> bytes:
        """Read a file from inside the container.

        `src_path` MUST be inside /workspace. Reads bounded at `max_bytes`
        to prevent memory blow-up.
        """

    @abstractmethod
    async def create_volume(self, volume_name: str) -> None:
        """Create a named volume. Idempotent — succeeds if it already exists."""

    @abstractmethod
    async def remove_volume(self, volume_name: str) -> None:
        """Remove a named volume and its contents."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_workspace_path(path: str) -> str:
    """Reject any path that isn't inside /workspace.

    Defense against path traversal in cp_to/cp_from. Even though the
    container is isolated, the parent must not be tricked into copying
    outside the kid's volume — the volume is the boundary the parent
    has agreed to expose."""
    # Normalize absolute paths
    if not path.startswith("/"):
        path = f"{_WORKSPACE}/{path}"
    normalized = os.path.normpath(path)
    if not normalized.startswith(f"{_WORKSPACE}/") and normalized != _WORKSPACE:
        raise ValueError(f"path must be inside {_WORKSPACE} (got {path!r})")
    return normalized


async def _run(cmd: list[str], stdin: bytes | None = None) -> tuple[int, str, str]:
    """Run a subprocess command; return (rc, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(stdin)
    return (
        proc.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


# ---------------------------------------------------------------------------
# DockerRuntime — the v1 shipping runtime
# ---------------------------------------------------------------------------


class DockerRuntime(ContainerRuntime):
    """Docker (or Docker-compatible — works with Colima too).

    Note: Colima exposes a `docker` CLI once `colima start` has run, so
    this class transparently handles Colima. A separate `ColimaRuntime`
    only adds auto-start for the VM; that's a v2 add."""

    name = "docker"

    def __init__(self, binary: str = "docker") -> None:
        self._bin = binary

    async def is_available(self) -> bool:
        if not shutil.which(self._bin):
            return False
        rc, _, _ = await _run([self._bin, "info"])
        return rc == 0

    async def start(
        self,
        *,
        image: str,
        name: str,
        env: dict[str, str],
        volume_name: str,
        memory_mb: int,
        cpus: float,
        pids_limit: int,
        network_mode: str,
        drop_capabilities: bool = True,
        read_only_rootfs: bool = True,
        no_new_privileges: bool = True,
        run_as_uid: int = 10001,
    ) -> str:
        if network_mode not in ("outbound-only", "none", "host"):
            raise ValueError(f"Unsupported network_mode: {network_mode!r}")

        cmd: list[str] = [
            self._bin,
            "run",
            "-d",
            "--name",
            name,
            f"--memory={memory_mb}m",
            f"--cpus={cpus}",
            f"--pids-limit={pids_limit}",
            "-v",
            f"{volume_name}:{_WORKSPACE}",
            # Make /tmp a small writable tmpfs so read-only rootfs is usable.
            "--tmpfs=/tmp:size=64m,mode=1777",
            # Add host-gateway hostname so the kid can reach the parent
            # gateway from inside the container on Linux.
            "--add-host=host.docker.internal:host-gateway",
        ]

        if drop_capabilities:
            cmd += ["--cap-drop=ALL"]
        if no_new_privileges:
            cmd += ["--security-opt=no-new-privileges"]
        if read_only_rootfs:
            cmd += ["--read-only"]
        if run_as_uid > 0:
            cmd += ["--user", f"{run_as_uid}:{run_as_uid}"]

        if network_mode == "host":
            cmd += ["--network=host"]
        elif network_mode == "none":
            cmd += ["--network=none"]
        # outbound-only is just the default Docker bridge for v1; v2 adds
        # an actual egress firewall via a sidecar (see KID_AGENTS_PLAN.md).

        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]

        cmd.append(image)

        rc, stdout, stderr = await _run(cmd)
        if rc != 0:
            raise ContainerRuntimeError(f"docker run failed: {stderr.strip()}")
        return stdout.strip()

    async def exec(self, container_id: str, cmd: list[str]) -> tuple[int, str, str]:
        return await _run([self._bin, "exec", container_id, *cmd])

    async def stop(self, container_id: str, timeout: int = 10) -> None:
        await _run([self._bin, "stop", "-t", str(timeout), container_id])

    async def remove(self, container_id: str) -> None:
        # -f tolerates a still-running container; this is destroy semantics.
        await _run([self._bin, "rm", "-f", container_id])

    async def inspect(self, container_id: str) -> dict[str, Any]:
        rc, stdout, stderr = await _run([self._bin, "inspect", container_id])
        if rc != 0:
            raise ContainerRuntimeError(f"docker inspect failed: {stderr.strip()}")
        try:
            data = json.loads(stdout)
            return data[0] if isinstance(data, list) and data else {}
        except (json.JSONDecodeError, IndexError) as e:
            raise ContainerRuntimeError(f"could not parse inspect output: {e}") from e

    async def cp_to_container(
        self, container_id: str, dest_path: str, data: bytes
    ) -> None:
        dest_path = _validate_workspace_path(dest_path)
        # `docker cp` reads a tar stream from stdin when target is "-".
        # We build a tar with one file and pipe it in.
        buf = BytesIO()
        # Path inside the tar must be relative; docker cp interprets it
        # relative to the container's target dir.
        with tarfile.open(fileobj=buf, mode="w") as tf:
            ti = tarfile.TarInfo(name=os.path.basename(dest_path))
            ti.size = len(data)
            ti.mode = 0o644
            tf.addfile(ti, BytesIO(data))
        rc, _, stderr = await _run(
            [self._bin, "cp", "-", f"{container_id}:{os.path.dirname(dest_path)}"],
            stdin=buf.getvalue(),
        )
        if rc != 0:
            raise ContainerRuntimeError(f"docker cp (to) failed: {stderr.strip()}")

    async def cp_from_container(
        self, container_id: str, src_path: str, max_bytes: int
    ) -> bytes:
        src_path = _validate_workspace_path(src_path)
        # Use a tarball stream to retrieve safely
        proc = await asyncio.create_subprocess_exec(
            self._bin,
            "cp",
            f"{container_id}:{src_path}",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Bound the read so a malicious kid can't blow up parent memory
        # with a multi-GB file. We read up to max_bytes of TAR; the inner
        # file is then capped at max_bytes too.
        assert proc.stdout is not None
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await proc.stdout.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes * 2:  # tar overhead margin
                proc.kill()
                await proc.wait()
                raise ContainerRuntimeError(
                    f"file at {src_path!r} exceeds max_bytes={max_bytes}"
                )
            chunks.append(chunk)
        rc = await proc.wait()
        stderr = (
            (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
        )
        if rc != 0:
            raise ContainerRuntimeError(f"docker cp (from) failed: {stderr.strip()}")
        # Extract the single file from the tar
        try:
            tf = tarfile.open(fileobj=BytesIO(b"".join(chunks)), mode="r")
            members = tf.getmembers()
            if not members:
                return b""
            f = tf.extractfile(members[0])
            if f is None:
                return b""
            data = f.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ContainerRuntimeError(
                    f"file at {src_path!r} exceeds max_bytes={max_bytes}"
                )
            return data
        except tarfile.TarError as e:
            raise ContainerRuntimeError(f"could not parse cp tar stream: {e}") from e

    async def create_volume(self, volume_name: str) -> None:
        # Idempotent: `docker volume create` returns 0 if it already exists.
        rc, _, stderr = await _run([self._bin, "volume", "create", volume_name])
        if rc != 0:
            raise ContainerRuntimeError(f"volume create failed: {stderr.strip()}")

    async def remove_volume(self, volume_name: str) -> None:
        # -f tolerates "doesn't exist"; this is destroy semantics.
        await _run([self._bin, "volume", "rm", "-f", volume_name])


# ---------------------------------------------------------------------------
# Runtime selection
# ---------------------------------------------------------------------------


async def detect_runtime(preference: list[str]) -> ContainerRuntime | None:
    """Pick the first available runtime from preference order.

    Returns None if none are available — caller decides whether that's a
    block (kid_spawn refused) or a warn (doctor).
    """
    for name in preference:
        if name in ("docker", "colima"):
            # Colima exposes a docker-compatible CLI once started, so we
            # use DockerRuntime for both. (Future: a ColimaRuntime that
            # auto-starts the VM if it's not running.)
            rt = DockerRuntime("docker")
            if await rt.is_available():
                # Annotate which runtime label was picked for telemetry
                rt.name = name
                return rt
        elif name == "podman":
            rt = DockerRuntime("podman")  # Podman's CLI is docker-compatible
            if await rt.is_available():
                rt.name = "podman"
                return rt
    return None
