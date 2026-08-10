"""Voice channel — spoken conversation with the agent.

Audio reaches this adapter one of two ways:

* **A connected node** (phone, laptop companion) posts a recorded clip
  through the gateway. This is the normal path once a device is paired.
* **The local microphone**, when ``sounddevice`` is installed and the
  operator starts a push-to-talk session from the terminal. Useful before
  any companion app exists, and for a headless box with a USB mic.

Both funnel into :meth:`VoiceAdapter.handle_audio`, which transcribes,
routes the text through the gateway exactly like a typed message, and
speaks the reply back.

One rule is enforced here rather than left to the model: **high-impact
actions require a fresh spoken confirmation.** Speech recognition is
lossy, rooms have other people in them, and "send it" is four phonemes
away from a dozen other things. An approval prompt that can be satisfied
by a mis-transcription is not an approval prompt, so the adapter asks
again, in words, and requires an explicit yes.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from channels.base import ChannelAdapter
from core.protocol import GatewayMessage

logger = logging.getLogger(__name__)

# Phrases accepted as an affirmative spoken confirmation. Deliberately
# short and explicit — "sure, whatever" should not authorize a payment.
_AFFIRMATIVE = re.compile(
    r"^\s*(yes|yeah|yep|confirm(ed)?|approved?|do it|go ahead|proceed)\b",
    re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"^\s*(no|nope|stop|cancel|don'?t|abort|deny|denied)\b", re.IGNORECASE
)


class VoiceAdapter(ChannelAdapter):
    """Speech in, speech out, over the normal gateway session machinery."""

    name = "voice"

    def __init__(
        self,
        config: Any,
        speech: Any,
        gateway_url: str = "ws://127.0.0.1:18789",
        user_id: str = "voice-operator",
    ) -> None:
        super().__init__(gateway_url)
        self._cfg = config
        self._speech = speech
        self._user_id = user_id
        self._session_id = f"voice:{user_id}"
        self._pending_approvals: dict[str, str] = {}
        self._speaking = asyncio.Lock()

    # ── lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        await self.connect_gateway()
        logger.info(
            "Voice channel ready (stt=%s, tts=%s/%s)",
            getattr(self._cfg, "stt_provider", "?"),
            getattr(self._cfg, "tts_provider", "?"),
            getattr(self._cfg, "tts_voice", "?"),
        )
        await self.gateway_listener()

    async def stop(self) -> None:
        self._running = False
        await self.disconnect_gateway()

    # ── inbound ─────────────────────────────────────────────────────

    async def handle_audio(self, audio_path: str | Path, language: str = "") -> str:
        """Transcribe a clip, run it as a turn, and speak the reply.

        Returns the spoken reply text (also useful for logging and tests).
        """
        from core.speech import SpeechError

        try:
            transcript = await self._speech.transcribe(audio_path, language=language)
        except SpeechError as exc:
            logger.error("Transcription failed: %s", exc)
            return ""

        if not transcript.strip():
            logger.info("Empty transcript — ignoring clip")
            return ""

        logger.info("[voice] heard: %s", transcript[:120])

        # A pending confirmation consumes this utterance rather than
        # starting a new turn: the operator is answering, not asking.
        if self._pending_approvals:
            handled = await self._resolve_spoken_approval(transcript)
            if handled:
                return ""

        response = await self.send_chat(
            content=transcript, user_id=self._user_id, session_id=self._session_id
        )
        reply = response.data.get("content", "")
        if reply:
            await self.speak(reply)
        return reply

    async def _resolve_spoken_approval(self, transcript: str) -> bool:
        """Interpret an utterance as a yes/no to the oldest pending ask."""
        request_id = next(iter(self._pending_approvals))
        if _AFFIRMATIVE.match(transcript):
            await self.send_approval(request_id, True)
            self._pending_approvals.pop(request_id, None)
            await self.speak("Confirmed.")
            return True
        if _NEGATIVE.match(transcript):
            await self.send_approval(request_id, False)
            self._pending_approvals.pop(request_id, None)
            await self.speak("Cancelled.")
            return True
        # Anything ambiguous is not consent. Re-ask rather than guess.
        await self.speak(
            "I didn't catch a clear yes or no. Say yes to proceed, or no to cancel."
        )
        return True

    async def listen_once(self, seconds: float = 8.0) -> str:
        """Record from the local microphone and process one utterance."""
        try:
            import sounddevice
            import soundfile
        except ImportError:
            logger.error(
                "Local microphone capture needs sounddevice and soundfile "
                "(pip install sounddevice soundfile), or send audio from a "
                "paired device instead."
            )
            return ""

        import tempfile

        sample_rate = 16000
        logger.info("[voice] listening for %.0fs…", seconds)
        recording = sounddevice.rec(
            int(seconds * sample_rate), samplerate=sample_rate, channels=1
        )
        await asyncio.to_thread(sounddevice.wait)

        path = Path(tempfile.mkstemp(suffix=".wav")[1])
        await asyncio.to_thread(soundfile.write, str(path), recording, sample_rate)
        try:
            return await self.handle_audio(path)
        finally:
            path.unlink(missing_ok=True)

    # ── outbound ────────────────────────────────────────────────────

    async def speak(self, text: str) -> None:
        """Synthesize and play *text*. Serialized so replies don't overlap."""
        from core.speech import SpeechError

        spoken = _strip_for_speech(text)
        if not spoken:
            return
        async with self._speaking:
            try:
                audio = await self._speech.synthesize(spoken)
            except SpeechError as exc:
                logger.error("Speech synthesis failed: %s", exc)
                return
            try:
                await self._speech.play(audio)
            finally:
                Path(audio).unlink(missing_ok=True)

    # ── gateway callbacks ───────────────────────────────────────────

    async def on_response(self, msg: GatewayMessage) -> None:
        content = msg.data.get("content", "")
        if content:
            await self.speak(content)

    async def on_approval_request(self, msg: GatewayMessage) -> None:
        """Ask out loud, and require a spoken yes before proceeding.

        The operator hears what is about to happen and answers in words.
        Nothing is approved by silence or by an ambiguous utterance.
        """
        request_id = msg.data.get("request_id", "")
        description = msg.data.get("description", "this action")
        self._pending_approvals[request_id] = description
        await self.speak(
            f"I need your confirmation before I {description}. Say yes to "
            "proceed, or no to cancel."
        )

    async def on_event(self, msg: GatewayMessage) -> None:
        content = msg.data.get("content") or msg.data.get("message") or ""
        if content:
            await self.speak(str(content))


def _strip_for_speech(text: str) -> str:
    """Turn a chat reply into something worth hearing.

    Markdown that reads well on screen is noise out loud: nobody wants
    backticks and pipe tables pronounced. Code blocks are summarized
    rather than read, since spoken code is unusable anyway.
    """
    cleaned = re.sub(
        r"```[\w-]*\n(.*?)```",
        lambda m: f" (a {len(m.group(1).splitlines())}-line code block) ",
        text,
        flags=re.DOTALL,
    )
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^\s*[|#>*\-+]+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("`", "").replace("**", "").replace("__", "")
    cleaned = re.sub(r"\n{2,}", ". ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()[:4000]
