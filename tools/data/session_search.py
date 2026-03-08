"""session_search — Search past conversation sessions via FTS5."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool, PermissionLevel, ToolResult

logger = logging.getLogger(__name__)


class SessionSearchTool(BaseTool):
    """Search past conversation sessions for relevant context."""

    @property
    def group(self) -> str:
        return "data"

    def __init__(self) -> None:
        self._db: Any = None

    @property
    def name(self) -> str:
        return "session_search"

    @property
    def description(self) -> str:
        return (
            "Search past conversation sessions using full-text search. "
            "Returns matching excerpts grouped by session with surrounding context. "
            "Supports FTS5 syntax: AND, OR, NOT, quoted phrases."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (supports FTS5 syntax: AND, OR, NOT, phrases)",
                },
                "channel": {
                    "type": "string",
                    "description": "Filter by channel (cli, telegram, discord, slack). Optional.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max sessions to return (default: 5)",
                },
                "days_back": {
                    "type": "integer",
                    "description": "Only search sessions from the last N days (default: 30)",
                },
            },
            "required": ["query"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if not self._db:
            return ToolResult(success=False, error="Database not available")

        query = params["query"].strip()
        if not query:
            return ToolResult(success=False, error="Search query cannot be empty")

        channel = params.get("channel")
        limit = min(params.get("limit", 5), 20)
        days_back = params.get("days_back", 30)

        try:
            # Search FTS5 index
            fts_query = query.replace("'", "''")

            # Find matching message IDs via FTS5
            match_sql = """
                SELECT sm.id, sm.session_id, sm.role, sm.content, sm.tool_name, sm.created_at,
                       snippet(session_messages_fts, 0, '>>>', '<<<', '...', 32) as snippet
                FROM session_messages_fts
                JOIN session_messages sm ON sm.id = session_messages_fts.rowid
                WHERE session_messages_fts MATCH ?
                  AND sm.created_at >= datetime('now', ?)
            """
            match_params: list[Any] = [fts_query, f"-{days_back} days"]

            if channel:
                match_sql += """
                  AND sm.session_id IN (
                      SELECT session_id FROM sessions WHERE channel = ?
                  )
                """
                match_params.append(channel)

            match_sql += " ORDER BY rank LIMIT 100"

            rows = await self._db.execute(match_sql, tuple(match_params))

            if not rows:
                return ToolResult(
                    success=True,
                    data={"results": [], "message": "No matching sessions found"},
                )

            # Group by session and build context windows
            sessions: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                sid = row["session_id"]
                if sid not in sessions:
                    sessions[sid] = []
                sessions[sid].append(
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "snippet": row["snippet"],
                        "tool_name": row["tool_name"],
                        "created_at": row["created_at"],
                    }
                )

            # Build results with context windows (limited to `limit` sessions)
            results = []
            for sid, matches in list(sessions.items())[:limit]:
                # Get session metadata
                session_rows = await self._db.execute(
                    "SELECT channel, user_id, created_at FROM sessions WHERE session_id = ?",
                    (sid,),
                )
                session_meta = {}
                if session_rows:
                    session_meta = {
                        "channel": session_rows[0]["channel"],
                        "user_id": session_rows[0]["user_id"],
                        "session_date": session_rows[0]["created_at"],
                    }

                # For each match, get surrounding context (5 messages before/after)
                context_windows = []
                for match in matches[:3]:  # Max 3 windows per session
                    context_rows = await self._db.execute(
                        """
                        SELECT role, content, tool_name, created_at
                        FROM session_messages
                        WHERE session_id = ? AND id BETWEEN ? AND ?
                        ORDER BY id
                        """,
                        (sid, match["id"] - 5, match["id"] + 5),
                    )
                    window = []
                    for cr in context_rows:
                        content = cr["content"]
                        if len(content) > 500:
                            content = content[:500] + "..."
                        msg = {"role": cr["role"], "content": content}
                        if cr["tool_name"]:
                            msg["tool"] = cr["tool_name"]
                        window.append(msg)
                    context_windows.append(window)

                results.append(
                    {
                        "session_id": sid[:8],
                        **session_meta,
                        "match_count": len(matches),
                        "excerpts": context_windows,
                    }
                )

            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "results": results,
                    "total_sessions": len(sessions),
                },
            )

        except Exception as e:
            error_str = str(e)
            if "no such table" in error_str:
                return ToolResult(
                    success=False,
                    error="Session search index not yet built. Messages will be indexed as conversations happen.",
                )
            return ToolResult(success=False, error=f"Search error: {error_str}")
