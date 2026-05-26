"""ABE voice-learning tools (Phase 10 — docs/76-ABE-FRAMEWORK.md).

The voice layer is the anti-slop quality gate on top of Phase 9
drafts. ``voice_extract`` reads operator-curated exemplars and
proposes a ``voice.yaml``; ``voice_show`` prints the active voice
contract for the current company; ``voice_lint`` runs a draft
through the contract and returns structured violations. The draft
tools (``email_draft``, ``outreach_draft``, ``post_draft``) call
``voice_lint`` inline before persisting — failures surface as the
draft tool's error so the LLM can revise in the next planning cycle.
"""

from tools.voice.extract_tool import VoiceExtractTool
from tools.voice.lint_tool import VoiceLintTool
from tools.voice.show_tool import VoiceShowTool

__all__ = [
    "VoiceExtractTool",
    "VoiceShowTool",
    "VoiceLintTool",
]
