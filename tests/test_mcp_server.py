"""v3.20 — PixCull addressable by an assistant, and only for questions.

Grepping first-party code for `mcp` returned nothing, while `serve_app`
already exposed scanning, semantic search, decisions and tether control
over HTTP on localhost.  An MCP wrapper makes that reachable by any
MCP-capable assistant at a fraction of the cost of a plugin per host.

Read-only is the feature.  This project's position is that the machine
proposes and the human decides; an assistant that could re-decide a
wedding through a tool call is the machine deciding, with the
photographer further from it than before.
"""
import io
import json

import pytest

from pixcull import mcp_server as M


def _call(method, params=None, mid=1):
    return M.handle({"jsonrpc": "2.0", "id": mid, "method": method,
                     "params": params or {}})


def test_a_write_tool_cannot_be_registered():
    """Structural, not documentary. A future write tool has to change the
    registration code, not just add a function."""
    with pytest.raises(ValueError) as exc:
        M.tool("cull_everything", "d", {}, readonly=False)(lambda: None)
    assert "read-only" in str(exc.value)


def test_every_registered_tool_is_a_question():
    """A tool whose name or description promises a change would be a
    contract this server must not offer."""
    banned = ("set_", "write", "delete", "cull_", "keep_", "decide",
              "update", "start", "stop", "retrain")
    for name in M._TOOLS:
        assert not any(name.startswith(b) or b in name for b in banned), name


def test_the_module_imports_nothing_that_writes():
    import inspect
    src = inspect.getsource(M)
    for writer in ("write_xmp", "record(", "_handle_save_annotation",
                   "run_pipeline", "TetherSession"):
        assert writer not in src, f"{writer} reachable from the MCP server"


def test_initialize_announces_the_protocol_and_the_server():
    r = _call("initialize")
    assert r["result"]["protocolVersion"] == M.PROTOCOL_VERSION
    assert r["result"]["serverInfo"]["name"] == M.SERVER_NAME


def test_tools_list_returns_schemas_a_client_can_use():
    tools = _call("tools/list")["result"]["tools"]
    assert tools
    for t in tools:
        assert t["name"] and t["description"]
        assert t["inputSchema"]["type"] == "object"


def test_an_unknown_tool_is_refused_not_guessed():
    r = _call("tools/call", {"name": "no_such_tool"})
    assert r["error"]["code"] == -32601


def test_bad_arguments_are_a_protocol_error_not_a_crash():
    r = _call("tools/call", {"name": "run_summary",
                             "arguments": {"nope": 1}})
    assert r["error"]["code"] == -32602


def test_a_tool_that_raises_becomes_an_error_response():
    M._TOOLS["_boom"] = {"description": "d", "schema": {},
                         "handler": lambda: 1 / 0}
    try:
        r = _call("tools/call", {"name": "_boom"})
        assert r["error"]["code"] == -32603
    finally:
        M._TOOLS.pop("_boom", None)


def test_a_missing_run_says_so_rather_than_returning_nothing():
    """An empty list reads as 'nothing in this shoot matches', which is a
    different and wrong answer."""
    r = _call("tools/call", {"name": "semantic_search",
                             "arguments": {"run_id": "nope", "query": "x"}})
    payload = json.loads(r["result"]["content"][0]["text"])
    assert payload["error"]


def test_an_unknown_method_is_refused():
    assert _call("resources/list")["error"]["code"] == -32601


def test_a_notification_gets_no_response():
    """JSON-RPC: a message with no id must not be answered."""
    assert M.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_the_stdio_loop_answers_line_by_line_and_survives_garbage():
    inp = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
        + "not json\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    )
    out = io.StringIO()
    M.serve(inp, out)
    lines = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    assert [l.get("id") for l in lines] == [1, None, 2]
    assert lines[1]["error"]["code"] == -32700
    assert lines[2]["result"]["tools"]
