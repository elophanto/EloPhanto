"""Speech-to-text and text-to-speech, behind one provider-agnostic seam.

Two consumers share this: the voice channel (a spoken conversation) and
media understanding (transcribing an audio or video attachment someone
sent). Keeping the provider choice in one place means adding a local
Whisper or swapping to ElevenLabs is a config change, not a rewrite of
both call sites.

Providers degrade in a deliberate order. Local options are preferred when
configured — audio is among the most personal data an operator has, and
shipping every utterance to a vendor should be a choice rather than the
default that happens because it was easiest to implement.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_OPENAI_STT = "https://api.openai.com/v1/audio/transcriptions"
_OPENAI_TTS = "https://api.openai.com/v1/audio/speech"
_ELEVENLABS_TTS = "https://api.elevenlabs.io/v1/text-to-speech"

# Formats we will hand to a transcriber. Anything else gets converted by
# ffmpeg first when it is available.
_NATIVE_AUDIO = frozenset({".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"})


class SpeechError(Exception):
    """Raised when transcription or synthesis fails."""


class SpeechEngine:
    """Transcribes audio and synthesizes speech using configured providers."""

    def __init__(
        self,
        *,
        stt_provider: str = "openai",
        stt_model: str = "whisper-1",
        tts_provider: str = "openai",
        tts_model: str = "tts-1",
        tts_voice: str = "alloy",
        api_key: str = "",
        elevenlabs_key: str = "",
    ) -> None:
        self.stt_provider = stt_provider
        self.stt_model = stt_model
        self.tts_provider = tts_provider
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self._api_key = api_key
        self._elevenlabs_key = elevenlabs_key

    # ── speech → text ───────────────────────────────────────────────

    async def transcribe(self, audio_path: str | Path, language: str = "") -> str:
        """Transcribe an audio or video file to text."""
        path = Path(audio_path)
        if not path.exists():
            raise SpeechError(f"No such audio file: {path}")

        prepared = await self._ensure_transcribable(path)
        try:
            if self.stt_provider == "local_whisper":
                return await self._transcribe_local(prepared, language)
            return await self._transcribe_openai(prepared, language)
        finally:
            if prepared != path:
                prepared.unlink(missing_ok=True)

    async def _ensure_transcribable(self, path: Path) -> Path:
        """Convert to wav when the extension is not one the API accepts."""
        if path.suffix.lower() in _NATIVE_AUDIO:
            return path
        if not shutil.which("ffmpeg"):
            raise SpeechError(
                f"{path.suffix} needs converting before transcription, but "
                "ffmpeg is not on PATH. Install ffmpeg, or supply one of: "
                + ", ".join(sorted(_NATIVE_AUDIO))
            )
        out = Path(tempfile.mkstemp(suffix=".wav")[1])
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            out.unlink(missing_ok=True)
            raise SpeechError(
                f"ffmpeg could not convert {path.name}: "
                f"{stderr.decode('utf-8', 'replace')[-300:]}"
            )
        return out

    async def _transcribe_openai(self, path: Path, language: str) -> str:
        if not self._api_key:
            raise SpeechError(
                "No API key for transcription. Store one in the vault under "
                "the key named by voice_channel.api_key_ref."
            )
        try:
            import httpx
        except ImportError as err:  # pragma: no cover
            raise SpeechError("httpx is required for transcription") from err

        data: dict[str, str] = {"model": self.stt_model}
        if language:
            data["language"] = language

        async with httpx.AsyncClient(timeout=180.0) as client:
            with path.open("rb") as handle:
                response = await client.post(
                    _OPENAI_STT,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files={"file": (path.name, handle, "application/octet-stream")},
                    data=data,
                )
        if response.status_code >= 400:
            raise SpeechError(
                f"Transcription failed ({response.status_code}): "
                f"{response.text[:300]}"
            )
        return str(response.json().get("text", "")).strip()

    async def _transcribe_local(self, path: Path, language: str) -> str:
        """Transcribe with a local whisper CLI — no audio leaves the machine."""
        binary = shutil.which("whisper") or shutil.which("whisper-cpp")
        if not binary:
            raise SpeechError(
                "stt_provider is 'local_whisper' but no whisper binary is on "
                "PATH. Install openai-whisper (pip install openai-whisper) or "
                "whisper.cpp."
            )
        with tempfile.TemporaryDirectory() as tmp:
            args = [binary, str(path), "--output_dir", tmp, "--output_format", "txt"]
            if language:
                args += ["--language", language]
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise SpeechError(
                    f"Local whisper failed: "
                    f"{stderr.decode('utf-8', 'replace')[-300:]}"
                )
            produced = list(Path(tmp).glob("*.txt"))
            if not produced:
                raise SpeechError("Local whisper produced no transcript.")
            return produced[0].read_text(encoding="utf-8").strip()

    # ── text → speech ───────────────────────────────────────────────

    async def synthesize(self, text: str, out_path: str | Path | None = None) -> Path:
        """Render *text* to an audio file and return its path."""
        if not text.strip():
            raise SpeechError("Nothing to speak.")
        destination = Path(out_path or tempfile.mkstemp(suffix=self._tts_suffix())[1])
        if self.tts_provider == "say":
            return await self._speak_macos(text, destination)
        if self.tts_provider == "elevenlabs":
            return await self._speak_elevenlabs(text, destination)
        return await self._speak_openai(text, destination)

    def _tts_suffix(self) -> str:
        return ".aiff" if self.tts_provider == "say" else ".mp3"

    async def _speak_openai(self, text: str, destination: Path) -> Path:
        if not self._api_key:
            raise SpeechError("No API key for speech synthesis.")
        try:
            import httpx
        except ImportError as err:  # pragma: no cover
            raise SpeechError("httpx is required for speech synthesis") from err

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                _OPENAI_TTS,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.tts_model,
                    "voice": self.tts_voice,
                    "input": text[:4000],
                },
            )
        if response.status_code >= 400:
            raise SpeechError(
                f"Speech synthesis failed ({response.status_code}): "
                f"{response.text[:300]}"
            )
        destination.write_bytes(response.content)
        return destination

    async def _speak_elevenlabs(self, text: str, destination: Path) -> Path:
        if not self._elevenlabs_key:
            raise SpeechError("No ElevenLabs API key configured.")
        try:
            import httpx
        except ImportError as err:  # pragma: no cover
            raise SpeechError("httpx is required for speech synthesis") from err

        voice_id = self.tts_voice or "21m00Tcm4TlvDq8ikWAM"
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{_ELEVENLABS_TTS}/{voice_id}",
                headers={
                    "xi-api-key": self._elevenlabs_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text[:4000],
                    "model_id": self.tts_model or "eleven_turbo_v2",
                },
            )
        if response.status_code >= 400:
            raise SpeechError(
                f"ElevenLabs synthesis failed ({response.status_code}): "
                f"{response.text[:300]}"
            )
        destination.write_bytes(response.content)
        return destination

    async def _speak_macos(self, text: str, destination: Path) -> Path:
        """Offline synthesis with the macOS `say` binary."""
        if not shutil.which("say"):
            raise SpeechError("tts_provider is 'say' but this is not macOS.")
        args = ["say", "-o", str(destination)]
        if self.tts_voice and self.tts_voice != "alloy":
            args += ["-v", self.tts_voice]
        args += [text[:4000]]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise SpeechError(
                f"`say` failed: {stderr.decode('utf-8', 'replace')[-200:]}"
            )
        return destination

    async def play(self, audio_path: str | Path) -> bool:
        """Play an audio file through the local speakers, best effort."""
        player = (
            shutil.which("afplay")
            or shutil.which("aplay")
            or shutil.which("ffplay")
            or shutil.which("mpv")
        )
        if not player:
            logger.warning("No audio player found; wrote %s instead", audio_path)
            return False
        args = [player, str(audio_path)]
        if player.endswith("ffplay"):
            args = [player, "-nodisp", "-autoexit", str(audio_path)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception as exc:
            logger.warning("Playback failed: %s", exc)
            return False


def engine_from_config(config: Any, vault: Any = None) -> SpeechEngine:
    """Build a :class:`SpeechEngine` from the ``voice_channel:`` section."""
    section = getattr(config, "voice_channel", None)
    api_key = ""
    elevenlabs_key = ""
    if vault is not None and section is not None:
        try:
            api_key = vault.get(getattr(section, "api_key_ref", "")) or ""
            if isinstance(api_key, dict):
                api_key = api_key.get("api_key") or api_key.get("token") or ""
            elevenlabs_key = vault.get("elevenlabs_api_key") or ""
            if isinstance(elevenlabs_key, dict):
                elevenlabs_key = elevenlabs_key.get("api_key", "")
        except Exception as exc:
            logger.debug("Speech key lookup failed: %s", exc)

    # Fall back to the configured OpenAI provider key — an operator who
    # already gave the agent an OpenAI key should not have to paste it
    # again to enable speech.
    if not api_key:
        try:
            provider = config.llm.providers.get("openai")
            api_key = getattr(provider, "api_key", "") or ""
        except Exception:
            api_key = ""

    return SpeechEngine(
        stt_provider=getattr(section, "stt_provider", "openai"),
        stt_model=getattr(section, "stt_model", "whisper-1"),
        tts_provider=getattr(section, "tts_provider", "openai"),
        tts_model=getattr(section, "tts_model", "tts-1"),
        tts_voice=getattr(section, "tts_voice", "alloy"),
        api_key=api_key,
        elevenlabs_key=elevenlabs_key,
    )
