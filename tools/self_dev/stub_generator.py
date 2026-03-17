"""Generate typed Python stubs for sandbox tool access.

Creates an `elophanto_tools.py` module that sandbox scripts can import.
Each function is a thin wrapper around the RPC socket.
"""

from __future__ import annotations

from tools.self_dev.rpc_server import ALLOWED_TOOLS

# Tool signatures — maps tool name to (args_str, docstring, params_dict_builder)
_TOOL_STUBS: dict[str, tuple[str, str, str]] = {
    "web_search": (
        "query: str, max_results: int = 5",
        "Search the web. Returns {'results': [{'title': ..., 'url': ..., 'snippet': ...}]}",
        '{"query": query, "max_results": max_results}',
    ),
    "web_extract": (
        "url: str",
        "Extract text content from a URL. Returns {'content': '...', 'title': '...'}",
        '{"url": url}',
    ),
    "file_read": (
        "path: str",
        "Read a file. Returns {'content': '...'}",
        '{"path": path}',
    ),
    "file_write": (
        "path: str, content: str",
        "Write content to a file. Returns {'written': True}",
        '{"path": path, "content": content}',
    ),
    "file_list": (
        "path: str = '.'",
        "List directory contents. Returns {'entries': [...]}",
        '{"path": path}',
    ),
    "knowledge_search": (
        "query: str, scope: str = 'all', limit: int = 5",
        "Search the knowledge base. Returns {'results': [...]}",
        '{"query": query, "scope": scope, "limit": limit}',
    ),
    "shell_execute": (
        "command: str, timeout: int = 30",
        "Run a shell command. Returns {'stdout': '...', 'returncode': 0}",
        '{"command": command, "timeout": timeout}',
    ),
    "agent_call": (
        'prompt: str, context: str = "", model: str = "auto", '
        'task_type: str = "analysis", max_tokens: int | None = None',
        (
            "Invoke a sub-instance of the agent on a focused prompt (RLM). "
            "Returns {'response': '...', 'model_used': '...', 'tokens': {...}, 'depth': N}. "
            "Use model='fast' for classification/simple tasks, model='strong' for deep analysis, "
            "or model='auto' (default) to let the router pick."
        ),
        '{"prompt": prompt, "context": context, "model": model, '
        '"task_type": task_type, "max_tokens": max_tokens}',
    ),
    "context_ingest": (
        "context_id: str = '', name: str = 'unnamed', "
        "files: list = None, text: str = '', source_label: str = 'inline_text'",
        (
            "Ingest files or text into a context store. "
            "Returns {'context_id': '...', 'chunks_created': N}. "
            "If context_id is empty, a new store is created."
        ),
        '{"context_id": context_id, "name": name, '
        '"files": files or [], "text": text, "source_label": source_label}',
    ),
    "context_query": (
        "context_id: str, query: str, max_chunks: int = 5",
        (
            "Semantic search over a context store. "
            "Returns {'results': [{'content': '...', 'source': '...', 'score': N}]}."
        ),
        '{"context_id": context_id, "query": query, "max_chunks": max_chunks}',
    ),
    "context_slice": (
        "context_id: str, source: str, start_line: int = None, end_line: int = None",
        (
            "Get exact content from a context store by source path and optional line range. "
            "Returns {'content': '...'}."
        ),
        '{"context_id": context_id, "source": source, '
        '"start_line": start_line, "end_line": end_line}',
    ),
    "context_index": (
        "context_id: str = ''",
        (
            "Get table of contents for a context store, or list all stores if "
            "context_id is empty. Returns {'index': '...'} or {'contexts': [...]}."
        ),
        '{"context_id": context_id}',
    ),
    "context_transform": (
        "context_id: str, operation: str, keyword: str = '', source: str = ''",
        (
            "Apply transformations: 'filter' (by keyword/source), 'group' (by source), "
            "'stats', 'sources'. Returns {'result': '...'}."
        ),
        '{"context_id": context_id, "operation": operation, '
        '"keyword": keyword, "source": source}',
    ),
}


def generate_stubs(socket_path: str) -> str:
    """Generate the elophanto_tools.py module source code."""
    lines = [
        '"""Auto-generated tool stubs for sandboxed code execution.',
        "",
        "Import this module to call EloPhanto tools from sandbox scripts.",
        "Each function sends an RPC call to the agent process.",
        '"""',
        "",
        "import json",
        "import socket as _socket",
        "",
        f'_SOCKET_PATH = "{socket_path}"',
        "_REQ_ID = 0",
        "",
        "",
        "def _rpc_call(tool: str, params: dict) -> dict:",
        '    """Send an RPC call to the agent and return the result."""',
        "    global _REQ_ID",
        "    _REQ_ID += 1",
        "    request = json.dumps({",
        '        "id": _REQ_ID,',
        '        "tool": tool,',
        '        "params": params,',
        "    })",
        "    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)",
        "    try:",
        "        sock.connect(_SOCKET_PATH)",
        '        sock.sendall(request.encode("utf-8") + b"\\n")',
        '        data = b""',
        "        while True:",
        "            chunk = sock.recv(65536)",
        "            if not chunk:",
        "                break",
        "            data += chunk",
        '            if b"\\n" in data:',
        "                break",
        '        response = json.loads(data.decode("utf-8").strip())',
        '        if not response.get("success"):',
        '            raise RuntimeError(response.get("error", "Unknown RPC error"))',
        '        return response.get("data", {})',
        "    finally:",
        "        sock.close()",
        "",
    ]

    # Generate a function for each allowed tool
    for tool_name in sorted(ALLOWED_TOOLS):
        stub = _TOOL_STUBS.get(tool_name)
        if not stub:
            continue
        args, doc, params_builder = stub
        lines.extend(
            [
                "",
                f"def {tool_name}({args}) -> dict:",
                f'    """{doc}"""',
                f'    return _rpc_call("{tool_name}", {params_builder})',
            ]
        )

    lines.append("")
    return "\n".join(lines)
