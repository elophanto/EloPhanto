"""Tests for core/kid_runtime.py — runtime selection + isolation invariants.

These tests do NOT require Docker to be running. They verify the
hardened-defaults discipline at the API surface and the path-validation
guard. Container-actually-running checks are integration-only.
"""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

from core.kid_runtime import (
    ContainerRuntime,
    ContainerRuntimeError,
    DockerRuntime,
    _validate_workspace_path,
    detect_runtime,
)


class TestPlanInvariants:
    """The KID_AGENTS_PLAN.md hardening rules are enforced HERE — these
    tests guard the rules, so weakening the API surface fails CI."""

    def test_start_has_no_bind_mounts_param(self) -> None:
        """No `bind_mounts` parameter ever leaks onto the runtime API."""
        sig = inspect.signature(ContainerRuntime.start)
        assert "bind_mounts" not in sig.parameters
        assert "volume_name" in sig.parameters

    def test_start_has_hardening_params_with_safe_defaults(self) -> None:
        sig = inspect.signature(ContainerRuntime.start)
        for hard in (
            "drop_capabilities",
            "read_only_rootfs",
            "no_new_privileges",
            "run_as_uid",
        ):
            assert hard in sig.parameters, f"missing hardening param: {hard}"
        assert sig.parameters["drop_capabilities"].default is True
        assert sig.parameters["read_only_rootfs"].default is True
        assert sig.parameters["no_new_privileges"].default is True
        assert sig.parameters["run_as_uid"].default == 10001


class TestWorkspacePathValidation:
    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError):
            _validate_workspace_path("../../etc/passwd")

    def test_rejects_absolute_outside_workspace(self) -> None:
        with pytest.raises(ValueError):
            _validate_workspace_path("/etc/passwd")

    def test_accepts_workspace_relative(self) -> None:
        assert _validate_workspace_path("output.txt") == "/workspace/output.txt"

    def test_accepts_workspace_absolute(self) -> None:
        assert (
            _validate_workspace_path("/workspace/output.txt") == "/workspace/output.txt"
        )

    def test_rejects_traversal_pretending_to_be_workspace(self) -> None:
        with pytest.raises(ValueError):
            _validate_workspace_path("/workspace/../../etc/passwd")


class TestDockerRunArgConstruction:
    """Verify DockerRuntime constructs `docker run` with the safety
    flags we promise. We mock subprocess so no docker daemon required."""

    @pytest.mark.asyncio
    async def test_run_command_includes_hardening_flags(self) -> None:
        rt = DockerRuntime("docker")
        captured: dict[str, list[str]] = {}

        async def fake_run(cmd, stdin=None):
            captured["cmd"] = cmd
            return (0, "containerid12345\n", "")

        with patch("core.kid_runtime._run", side_effect=fake_run):
            await rt.start(
                image="elophanto-kid:latest",
                name="test-kid",
                env={"ELOPHANTO_KID": "true"},
                volume_name="elophanto-kid-abc",
                memory_mb=512,
                cpus=0.5,
                pids_limit=200,
                network_mode="outbound-only",
            )
        cmd = captured["cmd"]
        assert "--cap-drop=ALL" in cmd
        assert "--security-opt=no-new-privileges" in cmd
        assert "--read-only" in cmd
        assert "--user" in cmd and "10001:10001" in cmd
        assert "--memory=512m" in cmd
        assert "--cpus=0.5" in cmd
        assert "--pids-limit=200" in cmd
        # Volume mount syntax — no host paths
        assert "-v" in cmd and "elophanto-kid-abc:/workspace" in cmd
        # No host-path bind mounts of any kind in the assembled args
        for arg in cmd:
            assert ":/var/run/docker.sock" not in arg
            assert "/proc:" not in arg
            assert "--privileged" not in arg

    @pytest.mark.asyncio
    async def test_unsupported_network_mode_rejected(self) -> None:
        rt = DockerRuntime("docker")
        with pytest.raises(ValueError):
            await rt.start(
                image="img",
                name="kid",
                env={},
                volume_name="vol",
                memory_mb=512,
                cpus=0.5,
                pids_limit=200,
                network_mode="bridge-with-firewall",  # not in the allowlist
            )

    @pytest.mark.asyncio
    async def test_run_failure_raises_runtime_error(self) -> None:
        rt = DockerRuntime("docker")

        async def fake_run(cmd, stdin=None):
            return (1, "", "no such image")

        with patch("core.kid_runtime._run", side_effect=fake_run):
            with pytest.raises(ContainerRuntimeError):
                await rt.start(
                    image="missing",
                    name="kid",
                    env={},
                    volume_name="vol",
                    memory_mb=512,
                    cpus=0.5,
                    pids_limit=200,
                    network_mode="outbound-only",
                )


class TestRuntimeDetection:
    @pytest.mark.asyncio
    async def test_detect_returns_none_when_nothing_available(self) -> None:
        with patch("shutil.which", return_value=None):
            rt = await detect_runtime(["docker", "podman", "colima"])
            assert rt is None

    @pytest.mark.asyncio
    async def test_detect_picks_docker_when_available(self) -> None:
        async def fake_run(cmd, stdin=None):
            return (0, "ok", "")

        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch("core.kid_runtime._run", side_effect=fake_run),
        ):
            rt = await detect_runtime(["docker", "podman", "colima"])
            assert rt is not None
            assert rt.name == "docker"

    @pytest.mark.asyncio
    async def test_detect_falls_through_when_docker_info_fails(self) -> None:
        """Binary present but daemon down — should keep looking."""
        # docker present, but `docker info` fails; podman absent.
        attempts: list[list[str]] = []

        async def fake_run(cmd, stdin=None):
            attempts.append(cmd)
            return (1, "", "Cannot connect to the Docker daemon")

        def fake_which(bin_name):
            return "/usr/bin/docker" if bin_name == "docker" else None

        with (
            patch("shutil.which", side_effect=fake_which),
            patch("core.kid_runtime._run", side_effect=fake_run),
        ):
            rt = await detect_runtime(["docker", "podman", "colima"])
            assert rt is None
