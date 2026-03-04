"""Desktop controller — local pyautogui + remote VM HTTP server.

Two modes:
- **local**: runs pyautogui directly on the host machine (no VM needed).
- **remote**: communicates with a VM running the OSWorld HTTP server.
"""

from __future__ import annotations

import abc
import asyncio
import base64
import io
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_RETRY_COUNT = 3
_RETRY_INTERVAL = 5  # seconds
_SCREENSHOT_TIMEOUT = 10  # seconds
_COMMAND_TIMEOUT = 90  # seconds

_PYAUTOGUI_PREFIX = (
    "import pyautogui; import time; pyautogui.FAILSAFE = False; {command}"
)


# ======================================================================
# Abstract base
# ======================================================================


class BaseDesktopController(abc.ABC):
    """Interface shared by local and remote desktop controllers."""

    @abc.abstractmethod
    async def screenshot(self) -> bytes | None: ...

    async def screenshot_base64(self) -> str | None:
        data = await self.screenshot()
        if data:
            return base64.b64encode(data).decode("ascii")
        return None

    @abc.abstractmethod
    async def accessibility_tree(self) -> str | None: ...

    @abc.abstractmethod
    async def cursor_position(self) -> dict[str, int] | None: ...

    @abc.abstractmethod
    async def screen_size(self) -> dict[str, int] | None: ...

    @abc.abstractmethod
    async def execute_pyautogui(self, command: str) -> dict[str, Any] | None: ...

    @abc.abstractmethod
    async def run_python(self, script: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def run_bash(
        self, script: str, timeout: int = 30, working_dir: str | None = None
    ) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def get_file(self, file_path: str) -> bytes | None: ...

    @abc.abstractmethod
    async def ping(self) -> bool: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


# ======================================================================
# Local controller — runs pyautogui on the host machine
# ======================================================================


class LocalDesktopController(BaseDesktopController):
    """Controls the local desktop directly via pyautogui."""

    async def screenshot(self) -> bytes | None:
        try:
            import pyautogui
            from PIL import Image

            img: Image.Image = pyautogui.screenshot()  # type: ignore[assignment]
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.error("Local screenshot failed: %s", e)
            return None

    async def accessibility_tree(self) -> str | None:
        return None  # not available locally without platform-specific a11y APIs

    async def cursor_position(self) -> dict[str, int] | None:
        try:
            import pyautogui

            x, y = pyautogui.position()
            return {"X": x, "Y": y}
        except Exception as e:
            logger.error("Local cursor_position failed: %s", e)
            return None

    async def screen_size(self) -> dict[str, int] | None:
        try:
            import pyautogui

            w, h = pyautogui.size()
            return {"width": w, "height": h}
        except Exception as e:
            logger.error("Local screen_size failed: %s", e)
            return None

    async def execute_pyautogui(self, command: str) -> dict[str, Any] | None:
        try:
            import time  # noqa: F401

            import pyautogui  # noqa: F401

            pyautogui.FAILSAFE = False
            exec(command)  # noqa: S102 — intentional; command comes from LLM
            return {"status": "ok", "output": "", "error": "", "returncode": 0}
        except Exception as e:
            logger.error("Local pyautogui exec failed: %s", e)
            return {"status": "error", "output": "", "error": str(e), "returncode": 1}

    async def run_python(self, script: str) -> dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                "-c",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_COMMAND_TIMEOUT
            )
            return {
                "status": "ok" if proc.returncode == 0 else "error",
                "output": stdout.decode(errors="replace"),
                "error": stderr.decode(errors="replace"),
                "returncode": proc.returncode,
            }
        except TimeoutError:
            return {"status": "error", "output": "", "error": "Timed out"}
        except Exception as e:
            return {"status": "error", "output": "", "error": str(e)}

    async def run_bash(
        self, script: str, timeout: int = 30, working_dir: str | None = None
    ) -> dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_shell(
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "status": "ok" if proc.returncode == 0 else "error",
                "output": stdout.decode(errors="replace"),
                "error": stderr.decode(errors="replace"),
                "returncode": proc.returncode,
            }
        except TimeoutError:
            return {
                "status": "error",
                "output": "",
                "error": f"Timed out after {timeout}s",
                "returncode": -1,
            }
        except Exception as e:
            return {"status": "error", "output": "", "error": str(e), "returncode": -1}

    async def get_file(self, file_path: str) -> bytes | None:
        try:
            from pathlib import Path

            return Path(file_path).read_bytes()
        except Exception as e:
            logger.error("Local get_file failed: %s", e)
            return None

    async def ping(self) -> bool:
        try:
            import pyautogui  # noqa: F401

            return True
        except ImportError:
            return False

    async def close(self) -> None:
        pass  # nothing to clean up


# ======================================================================
# Remote controller — talks to VM HTTP server
# ======================================================================


class DesktopController(BaseDesktopController):
    """Async HTTP client for a VM's OSWorld HTTP server."""

    def __init__(self, vm_ip: str, server_port: int = 5000) -> None:
        import aiohttp as _aiohttp

        self.vm_ip = vm_ip
        self.server_port = server_port
        self.base_url = f"http://{vm_ip}:{server_port}"
        self._aiohttp = _aiohttp
        self._session: Any = None

    async def _ensure_session(self) -> Any:
        _aiohttp = self._aiohttp
        if self._session is None or self._session.closed:
            self._session = _aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _is_valid_image(data: bytes | None) -> bool:
        """Check PNG/JPEG magic bytes."""
        if not data:
            return False
        if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
            return True
        if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
            return True
        return False

    # ------------------------------------------------------------------
    # Observation endpoints
    # ------------------------------------------------------------------

    async def screenshot(self) -> bytes | None:
        """GET /screenshot -> PNG bytes (with cursor)."""
        session = await self._ensure_session()
        for attempt in range(_RETRY_COUNT):
            try:
                async with session.get(
                    f"{self.base_url}/screenshot",
                    timeout=self._aiohttp.ClientTimeout(total=_SCREENSHOT_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if self._is_valid_image(data):
                            return data
                        logger.error(
                            "Invalid screenshot payload (attempt %d/%d)",
                            attempt + 1,
                            _RETRY_COUNT,
                        )
                    else:
                        logger.error("Screenshot failed: status %d", resp.status)
            except Exception as e:
                logger.error("Screenshot error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(_RETRY_INTERVAL)
        return None

    async def screenshot_base64(self) -> str | None:
        """Capture screenshot and return as base64 string."""
        data = await self.screenshot()
        if data:
            return base64.b64encode(data).decode("ascii")
        return None

    async def accessibility_tree(self) -> str | None:
        """GET /accessibility -> accessibility tree text."""
        session = await self._ensure_session()
        for attempt in range(_RETRY_COUNT):
            try:
                async with session.get(
                    f"{self.base_url}/accessibility",
                    timeout=self._aiohttp.ClientTimeout(total=_COMMAND_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json()
                        return body.get("AT")
                    logger.error("Accessibility tree failed: status %d", resp.status)
            except Exception as e:
                logger.error(
                    "Accessibility tree error (attempt %d): %s", attempt + 1, e
                )
            await asyncio.sleep(_RETRY_INTERVAL)
        return None

    async def terminal_output(self) -> str | None:
        """GET /terminal -> terminal output text."""
        session = await self._ensure_session()
        for attempt in range(_RETRY_COUNT):
            try:
                async with session.get(
                    f"{self.base_url}/terminal",
                    timeout=self._aiohttp.ClientTimeout(total=_COMMAND_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json()
                        return body.get("output")
                    logger.error("Terminal output failed: status %d", resp.status)
            except Exception as e:
                logger.error("Terminal output error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(_RETRY_INTERVAL)
        return None

    async def cursor_position(self) -> dict[str, int] | None:
        """GET /cursor_position -> {X, Y}."""
        session = await self._ensure_session()
        try:
            async with session.get(
                f"{self.base_url}/cursor_position",
                timeout=self._aiohttp.ClientTimeout(total=_SCREENSHOT_TIMEOUT),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.error("Cursor position error: %s", e)
        return None

    async def screen_size(self) -> dict[str, int] | None:
        """POST /screen_size -> {width, height}."""
        session = await self._ensure_session()
        try:
            async with session.post(
                f"{self.base_url}/screen_size",
                timeout=self._aiohttp.ClientTimeout(total=_SCREENSHOT_TIMEOUT),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.error("Screen size error: %s", e)
        return None

    # ------------------------------------------------------------------
    # Action endpoints
    # ------------------------------------------------------------------

    async def execute_pyautogui(self, command: str) -> dict[str, Any] | None:
        """POST /execute — run pyautogui command on VM.

        The command is wrapped with the standard pyautogui import prefix.
        """
        full_cmd = _PYAUTOGUI_PREFIX.format(command=command)
        command_list = ["python", "-c", full_cmd]
        payload = json.dumps({"command": command_list, "shell": False})

        session = await self._ensure_session()
        for attempt in range(_RETRY_COUNT):
            try:
                async with session.post(
                    f"{self.base_url}/execute",
                    headers={"Content-Type": "application/json"},
                    data=payload,
                    timeout=self._aiohttp.ClientTimeout(total=_COMMAND_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.error("Execute failed: status %d", resp.status)
            except TimeoutError:
                logger.error("Execute timed out (attempt %d)", attempt + 1)
                break
            except Exception as e:
                logger.error("Execute error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(_RETRY_INTERVAL)
        return None

    async def run_python(self, script: str) -> dict[str, Any]:
        """POST /run_python — run arbitrary Python script on VM."""
        payload = json.dumps({"code": script})
        session = await self._ensure_session()

        for attempt in range(_RETRY_COUNT):
            try:
                async with session.post(
                    f"{self.base_url}/run_python",
                    headers={"Content-Type": "application/json"},
                    data=payload,
                    timeout=self._aiohttp.ClientTimeout(total=_COMMAND_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    body = await resp.json()
                    return {
                        "status": "error",
                        "output": "",
                        "error": body.get("error", f"HTTP {resp.status}"),
                    }
            except TimeoutError:
                return {"status": "error", "output": "", "error": "Timed out"}
            except Exception as e:
                logger.error("run_python error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(_RETRY_INTERVAL)
        return {"status": "error", "output": "", "error": "Retry limit reached"}

    async def run_bash(
        self, script: str, timeout: int = 30, working_dir: str | None = None
    ) -> dict[str, Any]:
        """POST /run_bash_script — run bash script on VM."""
        payload = json.dumps(
            {"script": script, "timeout": timeout, "working_dir": working_dir}
        )
        session = await self._ensure_session()

        for attempt in range(_RETRY_COUNT):
            try:
                async with session.post(
                    f"{self.base_url}/run_bash_script",
                    headers={"Content-Type": "application/json"},
                    data=payload,
                    timeout=self._aiohttp.ClientTimeout(total=timeout + 100),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.error("run_bash failed: status %d", resp.status)
            except TimeoutError:
                return {
                    "status": "error",
                    "output": "",
                    "error": f"Timed out after {timeout}s",
                    "returncode": -1,
                }
            except Exception as e:
                logger.error("run_bash error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(_RETRY_INTERVAL)
        return {
            "status": "error",
            "output": "",
            "error": "Retry limit reached",
            "returncode": -1,
        }

    async def get_file(self, file_path: str) -> bytes | None:
        """POST /file — download file from VM."""
        session = await self._ensure_session()
        for attempt in range(_RETRY_COUNT):
            try:
                async with session.post(
                    f"{self.base_url}/file",
                    data={"file_path": file_path},
                    timeout=self._aiohttp.ClientTimeout(total=_COMMAND_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    logger.error("get_file failed: status %d", resp.status)
            except Exception as e:
                logger.error("get_file error (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(_RETRY_INTERVAL)
        return None

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """Check if the VM server is reachable."""
        session = await self._ensure_session()
        try:
            async with session.get(
                f"{self.base_url}/screenshot",
                timeout=self._aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False
