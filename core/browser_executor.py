"""Browser execution state tracking — evidence gating & stagnation detection.

Ported from aware-agent's task-executor.ts patterns. These ensure the agent:
1. Always observes the page after state-changing actions (evidence gating)
2. Doesn't repeat the same failing action endlessly (stagnation detection)
"""

from __future__ import annotations

import hashlib
from collections import deque
from typing import Any

# Tools that change page state — require observation afterward
STATE_CHANGING_TOOLS = frozenset(
    {
        "browser_navigate",
        "browser_go_back",
        "browser_click",
        "browser_click_text",
        "browser_click_batch",
        "browser_click_at",
        "browser_type",
        "browser_type_text",
        "browser_press_key",
        "browser_paste_html",
        "browser_select_option",
        "browser_scroll",
        "browser_scroll_container",
        "browser_drag_drop",
        "browser_drag_solve",
        "browser_drag_brute_force",
        "browser_hover",
        "browser_hover_element",
        "browser_pointer_path",
        "browser_eval",
        "browser_inject",
        "browser_new_tab",
        "browser_switch_tab",
        "browser_close_tab",
    }
)

# Tools that observe page state — satisfy evidence gating
OBSERVATION_TOOLS = frozenset(
    {
        "browser_extract",
        "browser_read_semantic",
        "browser_get_elements",
        "browser_screenshot",
        "browser_get_html",
        "browser_get_element_html",
        "browser_inspect_element",
        "browser_get_meta",
        "browser_deep_inspect",
        "browser_full_audit",
        "browser_dom_search",
        "browser_read_scripts",
        "browser_extract_hidden_code",
        "browser_get_console",
        "browser_get_network",
        "browser_get_response_body",
        "browser_get_storage",
        "browser_get_cookies",
        "browser_get_element_box",
    }
)

_STAGNATION_THRESHOLD = 3  # Same action repeated this many times → stagnation
_FINGERPRINT_HISTORY = 10  # How many fingerprints to keep


class BrowserExecutionState:
    """Tracks browser execution state for evidence gating and stagnation detection."""

    def __init__(self) -> None:
        self.needs_observation: bool = False
        self.unobserved_changes: int = 0
        self._action_history: deque[str] = deque(maxlen=20)
        self._page_fingerprints: deque[str] = deque(maxlen=_FINGERPRINT_HISTORY)
        self._last_fingerprint: str = ""

    def after_tool(self, tool_name: str, result: dict[str, Any] | None = None) -> None:
        """Update state after a tool execution.

        Call this after every browser tool call to maintain evidence gating state.
        """
        if tool_name in STATE_CHANGING_TOOLS:
            self.needs_observation = True
            self.unobserved_changes += 1
            self._action_history.append(tool_name)

        if tool_name in OBSERVATION_TOOLS:
            self.needs_observation = False
            self.unobserved_changes = 0

            # Update page fingerprint from observation result
            if result:
                fp = self._compute_fingerprint(result)
                if fp:
                    self._page_fingerprints.append(fp)
                    self._last_fingerprint = fp

    def get_evidence_notice(self) -> str | None:
        """Return a notice if the agent needs to observe before acting.

        Returns None if no observation is needed, otherwise a guidance message.
        """
        if not self.needs_observation:
            return None

        if self.unobserved_changes >= 2:
            return (
                f"WARNING: {self.unobserved_changes} state-changing actions without observation. "
                "You MUST call browser_extract, browser_get_elements, or browser_screenshot "
                "before your next action to see the current page state."
            )
        return (
            "After a state-changing action, observe the page before proceeding. "
            "Call browser_extract or browser_get_elements to see what changed."
        )

    def check_stagnation(
        self, tool_name: str, args: dict[str, Any] | None = None
    ) -> str | None:
        """Check if the same action is being repeated without progress.

        Returns a stagnation notice if detected, None otherwise.
        """
        # Build action signature from tool name + key args
        action_sig = self._action_signature(tool_name, args)

        # Count consecutive repetitions of this exact action
        consecutive = 0
        for past in reversed(self._action_history):
            if past == action_sig:
                consecutive += 1
            else:
                break

        if consecutive >= _STAGNATION_THRESHOLD:
            return (
                f"STAGNATION DETECTED: '{tool_name}' has been called {consecutive} times "
                "in a row without the page changing. Try a completely different approach: "
                "use a different tool, different selector, or re-read the page to understand "
                "what's happening."
            )

        # Detect submit-loop: type → click submit text → type → click submit text
        # This catches the X/Twitter failure where "Post" hits the sidebar button
        _submit_texts = {"post", "reply", "submit", "publish", "send", "tweet"}
        if tool_name in ("browser_click_text", "browser_click"):
            click_text = str((args or {}).get("text", "")).lower()
            if click_text in _submit_texts:
                # Count how many times we've typed then clicked this submit text
                _submit_loops = 0
                _saw_type = False
                for past in reversed(list(self._action_history)):
                    sig_parts = past.split("|")
                    past_tool = sig_parts[0] if sig_parts else ""
                    if past_tool in ("browser_type_text", "browser_type"):
                        _saw_type = True
                    elif past_tool in ("browser_click_text", "browser_click"):
                        past_text = ""
                        for p in sig_parts:
                            if p.startswith("text="):
                                past_text = p[5:].lower()
                        if past_text in _submit_texts and _saw_type:
                            _submit_loops += 1
                            _saw_type = False
                    else:
                        if past_tool not in (
                            "browser_screenshot",
                            "browser_extract",
                            "browser_get_elements",
                        ):
                            break
                if _submit_loops >= 2:
                    return (
                        f"SUBMIT LOOP DETECTED: You've typed content and clicked '{click_text}' "
                        f"{_submit_loops} times without the post being submitted. "
                        "On X/Twitter, browser_click_text('Post') clicks the SIDEBAR nav button "
                        "(opening a new compose modal) instead of submitting. "
                        "FIX: Use browser_click with the specific element INDEX of the submit "
                        "button INSIDE the composer. For replies, use browser_click_text('Reply', exact=True). "
                        "Look at the element list for a button with data-testid='tweetButtonInline' "
                        "or the button nearest the compose textarea."
                    )

        return None

    def reset(self) -> None:
        """Reset all state (e.g., for a new task)."""
        self.needs_observation = False
        self.unobserved_changes = 0
        self._action_history.clear()
        self._page_fingerprints.clear()
        self._last_fingerprint = ""

    @staticmethod
    def _compute_fingerprint(result: dict[str, Any]) -> str:
        """Compute a page fingerprint from an observation result."""
        parts: list[str] = []

        # URL
        url = result.get("url", "")
        if url:
            parts.append(url)

        # Title
        title = result.get("title", "")
        if title:
            parts.append(title)

        # Text content (first 500 chars)
        text = result.get("text", "") or result.get("content", "")
        if isinstance(text, str) and text:
            parts.append(text[:500])

        # Element count
        elements = result.get("elements")
        if isinstance(elements, list):
            parts.append(f"elements:{len(elements)}")

        if not parts:
            return ""

        combined = "|".join(parts)
        return hashlib.md5(combined.encode()).hexdigest()[:12]

    @staticmethod
    def _action_signature(tool_name: str, args: dict[str, Any] | None) -> str:
        """Create a signature for an action (tool + key args)."""
        if not args:
            return tool_name

        # Include key identifying args in the signature
        key_parts = [tool_name]
        for key in sorted(args.keys()):
            val = args[key]
            if isinstance(val, (str, int, float, bool)):
                key_parts.append(f"{key}={val}")
        return "|".join(key_parts)
