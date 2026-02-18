"""Telegram message formatting utilities.

Converts agent markdown to Telegram MarkdownV2, splits long messages
at natural boundaries, and builds inline keyboard markup.
"""

from __future__ import annotations

import re

_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!"

# Markers that won't be touched by MarkdownV2 escaping
_B0 = "\x02"  # bold open
_B1 = "\x03"  # bold close
_I0 = "\x04"  # italic open
_I1 = "\x05"  # italic close
_L0 = "\x06"  # link text open
_L1 = "\x07"  # link text close / url open
_L2 = "\x08"  # link url close


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r"([" + re.escape(_ESCAPE_CHARS) + r"])", r"\\\1", text)


def to_telegram_markdown(text: str) -> str:
    """Convert standard markdown to Telegram MarkdownV2.

    Handles bold, italic, code blocks, inline code, and links.
    Falls back to escaped plain text for unsupported constructs.
    """
    lines = text.split("\n")
    result: list[str] = []
    in_code_block = False

    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            if in_code_block:
                lang = line.strip().removeprefix("```").strip()
                result.append(f"```{lang}" if lang else "```")
            else:
                result.append("```")
            continue

        if in_code_block:
            result.append(line)
            continue

        # Skip markdown table separator lines
        if re.match(r"^\s*\|[-\s|:]+\|\s*$", line):
            continue

        converted = _convert_inline(line)
        result.append(converted)

    return "\n".join(result)


def _convert_inline(line: str) -> str:
    """Convert inline markdown elements in a single line."""
    parts: list[str] = []
    segments = re.split(r"(`[^`]+`)", line)
    for seg in segments:
        if seg.startswith("`") and seg.endswith("`"):
            parts.append(seg)
        else:
            converted = _escape_and_format(seg)
            parts.append(converted)
    return "".join(parts)


def _escape_and_format(text: str) -> str:
    """Escape text and convert bold/italic/link markers."""
    # Replace markdown markers with control characters BEFORE escaping
    text = re.sub(r"\*\*(.+?)\*\*", rf"{_B0}\1{_B1}", text)
    text = re.sub(r"\*(.+?)\*", rf"{_I0}\1{_I1}", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", rf"{_L0}\1{_L1}\2{_L2}", text)

    # Escape all special characters (control chars are untouched)
    text = escape_markdown_v2(text)

    # Replace control characters with MarkdownV2 formatting
    text = text.replace(_B0, "*").replace(_B1, "*")
    text = text.replace(_I0, "_").replace(_I1, "_")
    text = re.sub(
        re.escape(_L0) + r"(.+?)" + re.escape(_L1) + r"(.+?)" + re.escape(_L2),
        r"[\1](\2)",
        text,
    )

    return text


def to_plain_text(text: str) -> str:
    """Strip markdown formatting for plain text fallback."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|[-\s|:]+\|\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a long message at paragraph boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    paragraphs = text.split("\n\n")
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2

        if current_len + para_len > max_len and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0

        if len(para) > max_len:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            lines = para.split("\n")
            line_chunk: list[str] = []
            line_len = 0
            for ln in lines:
                if line_len + len(ln) + 1 > max_len and line_chunk:
                    chunks.append("\n".join(line_chunk))
                    line_chunk = []
                    line_len = 0
                line_chunk.append(ln)
                line_len += len(ln) + 1
            if line_chunk:
                chunks.append("\n".join(line_chunk))
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks
