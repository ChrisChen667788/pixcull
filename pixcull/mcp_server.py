"""v3.20 — PixCull as an MCP tool server, read-only.

Grepping first-party code for `mcp` returned nothing.  Meanwhile
`serve_app` already exposes scanning, semantic search, decisions and
tether control over HTTP on localhost.  A thin MCP wrapper makes all of
that addressable by any MCP-capable assistant, which is the integration
shape the Firefly-agent and Lightroom-MCP entries in the competitive
research all point at — and a fraction of the cost of writing a plugin
per host application.

NO SDK, ON PURPOSE

MCP over stdio is newline-delimited JSON-RPC 2.0.  Implementing the three
methods this needs is about a hundred lines; taking a dependency for it
would put a moving third-party package in the import path of a tool whose
whole pitch is that it runs on the photographer's own machine.

READ-ONLY IS THE FEATURE, NOT A LIMITATION

Every tool here answers a question.  None of them changes a decision,
writes a sidecar, starts a run or touches a photograph.  This project's
position is that the machine proposes and the human decides, and an
assistant that could re-decide a wedding through a tool call would be the
same thing as the machine deciding — with the photographer even further
from it.

The guard is structural rather than documentary: a handler is registered
through :func:`tool`, which refuses anything not declared read-only, and
`dispatch` refuses a name that is not in the registry.  A future write
tool has to change the registration code, not just add a function.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "pixcull"

#: name -> {description, schema, handler}
_TOOLS: dict[str, dict[str, Any]] = {}


def tool(name: str, description: str, schema: dict, *, readonly: bool):
    """Register one MCP tool. Refuses anything not read-only."""
    if not readonly:
        raise ValueError(
            f"{name}: this server is read-only by design. A tool that "
            f"changes a decision would let an assistant re-cull a "
            f"photographer's shoot through a tool call."
        )

    def _wrap(fn: Callable[..., Any]):
        _TOOLS[name] = {"description": description, "schema": schema,
                        "handler": fn}
        return fn
    return _wrap


# ---------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------

@tool("list_runs", "List the culling runs on this machine.",
      {"type": "object", "properties": {}}, readonly=True)
def _list_runs() -> Any:
    """Runs on disk, not only the ones a live server happens to remember.

    `_RUNS` is a server-process dict; an assistant asking this question
    has usually not started one. `_reload_run_from_disk` is the same
    reconstruction the thumbnail path uses after a restart.
    """
    from pixcull.report.serve_app import _DEMO_ROOT, _reload_run_from_disk
    out = []
    root = _DEMO_ROOT
    if not root.exists():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        run = _reload_run_from_disk(d.name)
        if run is None:
            continue
        out.append({"run_id": d.name,
                    "folder": str(run.get("folder") or ""),
                    "output_dir": str(run.get("output_dir") or "")})
    return out


@tool("run_summary", "Decision counts and settings for one run.",
      {"type": "object",
       "properties": {"run_id": {"type": "string"}},
       "required": ["run_id"]}, readonly=True)
def _run_summary(run_id: str) -> Any:
    from pixcull.report.serve_app import _build_results
    got = _build_results(str(run_id))
    if got is None:
        return {"error": "no such run"}
    rows, meta = got
    counts: dict[str, int] = {}
    for r in rows:
        d = str(r.get("decision") or "")
        counts[d] = counts.get(d, 0) + 1
    return {"run_id": run_id, "n": len(rows), "decisions": counts,
            "vertical": (meta or {}).get("vertical")}


@tool("decisions", "Per-photo decisions and scores for one run.",
      {"type": "object",
       "properties": {"run_id": {"type": "string"},
                      "limit": {"type": "integer"}},
       "required": ["run_id"]}, readonly=True)
def _decisions(run_id: str, limit: int = 200) -> Any:
    from pixcull.report.serve_app import _build_results
    got = _build_results(str(run_id))
    if got is None:
        return {"error": "no such run"}
    rows, _ = got
    limit = max(1, min(1000, int(limit)))
    return [{"filename": r.get("filename"),
             "decision": r.get("decision"),
             "score_final": r.get("score_final"),
             "scene": r.get("scene")}
            for r in rows[:limit]]


@tool("semantic_search", "Find photos in a run by natural-language query.",
      {"type": "object",
       "properties": {"run_id": {"type": "string"},
                      "query": {"type": "string"},
                      "k": {"type": "integer"}},
       "required": ["run_id", "query"]}, readonly=True)
def _semantic_search(run_id: str, query: str, k: int = 8) -> Any:
    """CLIP text->image search over one run's embeddings cache.

    Goes through the same `semantic_search` module the HTTP endpoint
    uses; reimplementing the ranking here would be a second copy waiting
    to drift from the first.
    """
    from pathlib import Path

    from pixcull.report.serve_app import _get_run, _reload_run_from_disk
    run = _get_run(str(run_id)) or _reload_run_from_disk(str(run_id))
    if run is None:
        return {"error": "no such run"}
    cache_path = Path(run["output_dir"]) / "embeddings.npz"
    if not cache_path.exists():
        # An honest "not built" beats an empty list that reads as
        # "nothing in this shoot matches".
        return {"error": "this run has no embeddings cache yet"}
    try:
        from pixcull.scoring.semantic_search import (
            load_embeddings_cache, search,
        )
        cache = load_embeddings_cache(cache_path)
        hits = search(str(query), cache=cache, k=max(1, min(50, int(k))))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    return [{"filename": h[0], "score": float(h[1])}
            if isinstance(h, (list, tuple)) else h for h in hits]


# ---------------------------------------------------------------------
# JSON-RPC
# ---------------------------------------------------------------------

def tool_list() -> list[dict]:
    return [{"name": n, "description": t["description"],
             "inputSchema": t["schema"]} for n, t in sorted(_TOOLS.items())]


def dispatch(name: str, arguments: dict | None) -> Any:
    """Call one registered tool. An unknown name is refused, not guessed."""
    spec = _TOOLS.get(name)
    if spec is None:
        raise KeyError(f"unknown tool: {name}")
    return spec["handler"](**(arguments or {}))


def handle(message: dict) -> dict | None:
    """One JSON-RPC request in, one response out (None for notifications)."""
    mid = message.get("id")
    method = message.get("method") or ""
    params = message.get("params") or {}

    def _ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _err(code, msg):
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": code, "message": msg}}

    if method == "initialize":
        from pixcull import __version__ as _v
        return _ok({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": str(_v)},
        })
    if method == "tools/list":
        return _ok({"tools": tool_list()})
    if method == "tools/call":
        try:
            out = dispatch(str(params.get("name") or ""),
                           params.get("arguments"))
        except KeyError as exc:
            return _err(-32601, str(exc))
        except TypeError as exc:
            return _err(-32602, f"bad arguments: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _err(-32603, f"{type(exc).__name__}: {exc}")
        return _ok({"content": [{"type": "text",
                                 "text": json.dumps(out, ensure_ascii=False,
                                                    default=str)}]})
    if mid is None:
        return None            # a notification; nothing to answer
    return _err(-32601, f"unknown method: {method}")


def serve(stdin=None, stdout=None) -> None:
    """Read requests from stdin, write responses to stdout, until EOF."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": "parse error"}}) + "\n")
            stdout.flush()
            continue
        resp = handle(msg)
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False,
                                    default=str) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
