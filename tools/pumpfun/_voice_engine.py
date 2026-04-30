"""TTS voice engine — internal helper for pump_livestream voice mode.

Spawned as a sibling of the ffmpeg supervisor when ``start_stream``
runs with ``voice=True``. Watches a JSONL queue file for things the
agent wants to say, renders each line via OpenAI TTS, and streams
the resulting audio as raw 16-bit signed little-endian PCM (48 kHz
mono) into a named FIFO that ffmpeg reads as its audio input.

Why PCM/FIFO and not Opus chunks? Concat'ing pre-encoded Opus blobs
is finicky (page boundaries, granule positions). Raw PCM is the
simplest interchange — write samples, ffmpeg encodes to Opus on the
way out.

When the queue is empty the engine writes silence so ffmpeg's audio
buffer never underruns. Without continuous writes the WHIP/RTMP
publisher would stall at the first idle gap.

Invoked as ``python -m tools.pumpfun._voice_engine``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

import httpx

logger = logging.getLogger("pumpfun.voice")
logging.basicConfig(
    level=logging.INFO, format="[voice] %(asctime)s %(message)s", stream=sys.stdout
)

# Audio constants — must match the ffmpeg input cmd in build_ffmpeg_cmd
SAMPLE_RATE = 48000
CHANNELS = 1
BYTES_PER_SAMPLE = 2  # int16 LE

# How much silence to push when the queue is empty. 100 ms keeps the
# ffmpeg buffer warm without flooding it; total write bandwidth is
# 48000 * 2 * 1 * 0.1 = 9.6 KB / 100 ms.
_SILENCE_CHUNK_MS = 100
_SILENCE_BYTES = b"\x00" * (
    SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE * _SILENCE_CHUNK_MS // 1000
)

# OpenAI TTS endpoint — model + voice are configurable at start time
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

_running = True


def _handle_signal(_signum: int, _frame: object) -> None:
    global _running
    _running = False


def _tts_pcm(api_key: str, text: str, model: str, voice: str) -> bytes:
    """Render ``text`` to 48 kHz mono PCM via OpenAI's TTS API.

    OpenAI returns ``response_format: pcm`` as raw 24 kHz s16le. We
    upsample to 48 kHz by simple sample doubling — TTS is heavily
    bandlimited so the artifacts are inaudible. Avoids pulling
    librosa/numpy as a dep.
    """
    body = {
        "model": model,
        "voice": voice,
        "input": text,
        "response_format": "pcm",
    }
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            OPENAI_TTS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"TTS HTTP {r.status_code}: {r.text[:300]}")
    pcm_24k = r.content
    if not pcm_24k:
        raise RuntimeError("TTS returned empty audio")

    # Upsample 24 kHz → 48 kHz by sample doubling.
    out = bytearray(len(pcm_24k) * 2)
    for i in range(0, len(pcm_24k), 2):
        out[i * 2] = pcm_24k[i]
        out[i * 2 + 1] = pcm_24k[i + 1] if i + 1 < len(pcm_24k) else 0
        out[i * 2 + 2] = pcm_24k[i]
        out[i * 2 + 3] = pcm_24k[i + 1] if i + 1 < len(pcm_24k) else 0
    return bytes(out)


def _read_pending(queue_file: Path, cursor_path: Path) -> tuple[list[str], int]:
    """Read new JSONL entries past ``cursor_path``'s recorded byte offset."""
    if not queue_file.exists():
        return [], 0
    cursor = 0
    if cursor_path.exists():
        try:
            cursor = int(cursor_path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            cursor = 0
    with queue_file.open("rb") as f:
        f.seek(cursor)
        data = f.read()
        new_cursor = f.tell()
    if not data:
        return [], cursor
    texts: list[str] = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            text = (entry.get("text") or "").strip()
            if text:
                texts.append(text)
        except json.JSONDecodeError:
            pass
    return texts, new_cursor


def main() -> None:
    parser = argparse.ArgumentParser(prog="pumpfun-voice-engine")
    parser.add_argument("--queue-file", required=True)
    parser.add_argument("--cursor-file", required=True)
    parser.add_argument("--pcm-fifo", required=True)
    parser.add_argument("--stop-marker", required=True)
    parser.add_argument("--openai-api-key", required=True)
    parser.add_argument("--model", default="tts-1")
    parser.add_argument("--voice", default="onyx")
    args = parser.parse_args()

    queue_file = Path(args.queue_file)
    cursor_file = Path(args.cursor_file)
    fifo = Path(args.pcm_fifo)
    stop_marker = Path(args.stop_marker)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Open FIFO blocking — ffmpeg must already be reading. Writing
    # blocks until the reader connects which is the right semantics.
    logger.info("opening fifo (blocks until ffmpeg attaches): %s", fifo)
    fd = os.open(str(fifo), os.O_WRONLY)
    logger.info("fifo open; entering loop")

    last_silence_ts = time.monotonic()
    try:
        while _running:
            if stop_marker.exists():
                logger.info("stop marker present, exiting")
                break
            texts, new_cursor = _read_pending(queue_file, cursor_file)
            if texts:
                for text in texts:
                    logger.info("speaking %d chars: %r", len(text), text[:80])
                    try:
                        pcm = _tts_pcm(
                            args.openai_api_key, text, args.model, args.voice
                        )
                    except Exception as e:
                        logger.exception("TTS failed: %s", e)
                        # Skip this line; cursor still advances so we
                        # don't loop on a poison message.
                        continue
                    # Stream PCM in chunks so signals can interrupt.
                    chunk_size = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE  # 1 s
                    for off in range(0, len(pcm), chunk_size):
                        if not _running or stop_marker.exists():
                            break
                        os.write(fd, pcm[off : off + chunk_size])
                    # Brief pause between utterances for natural pacing.
                    os.write(fd, _SILENCE_BYTES * 5)  # ~500 ms
                cursor_file.write_text(str(new_cursor), encoding="utf-8")
                last_silence_ts = time.monotonic()
            else:
                # Idle: keep the audio buffer warm with silence so
                # ffmpeg doesn't stall.
                os.write(fd, _SILENCE_BYTES)
                # Brief sleep so we don't burn CPU when truly idle.
                # 100 ms between writes pairs with 100 ms silence chunks.
                if time.monotonic() - last_silence_ts < 0.1:
                    time.sleep(0.05)
    except BrokenPipeError:
        logger.info("ffmpeg closed the pipe; exiting")
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    logger.info("voice engine exiting cleanly")


if __name__ == "__main__":
    main()
