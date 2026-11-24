# MIT License
#
# Copyright (c) 2025-2026 ericsmacedo
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


"""Test MCP Server."""

import io
import json

from hdl_parser import Project
from hdl_parser._mcp import PROTOCOL_VERSIONS, TOOLS, Server, serve

from .conftest import objects


def _project(tmp_path):
    (tmp_path / "top.sv").write_text("module top;\n  sub u_sub ();\nendmodule\n")
    (tmp_path / "sub.sv").write_text("module sub (input logic a);\nendmodule\n")
    return lambda: Project.from_dir(tmp_path)


def _session(load, *messages):
    lines = (message if isinstance(message, str) else json.dumps(message) for message in messages)
    stdin = io.StringIO("".join(f"{line}\n" for line in lines))
    stdout = io.StringIO()
    serve(load, stdin, stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def _call(id_, tool, **arguments):
    return {"jsonrpc": "2.0", "id": id_, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}


def test_session(tmp_path):
    """Initialize, List Tools, Call A Tool."""
    responses = _session(
        _project(tmp_path),
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        "",
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        _call(3, "where_used", name="sub"),
        {"jsonrpc": "2.0", "id": 4, "method": "ping"},
    )
    assert [response["id"] for response in responses] == [1, 2, 3, 4]
    assert responses[0]["result"]["protocolVersion"] == "2025-03-26"
    assert responses[0]["result"]["serverInfo"]["name"] == "hdl-parser"
    names = [tool["name"] for tool in responses[1]["result"]["tools"]]
    assert names == [
        "module",
        "hierarchy",
        "where_used",
        "find",
        "diagnostics",
        "elaborate",
        "evaluate",
        "drivers",
        "loads",
        "trace",
        "reload",
    ]
    result = responses[2]["result"]
    assert result["isError"] is False
    assert objects(result["structuredContent"]["result"])[0]["inst"] == "top.sv:top.u_sub"
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    assert responses[3]["result"] == {}


def test_unknown_version(tmp_path):
    """The Latest Version Is Offered."""
    message = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}
    (response,) = _session(_project(tmp_path), message)
    assert response["result"]["protocolVersion"] == PROTOCOL_VERSIONS[0]


def test_errors(tmp_path, monkeypatch):
    """Errors Never Stop The Server."""
    from hdl_parser import _mcp  # noqa: PLC0415

    def failing(project, **kwargs):
        raise ValueError("bug")

    monkeypatch.setitem(_mcp._QUERIES, "find", failing)
    responses = _session(
        _project(tmp_path),
        "garbage",
        {"id": 1, "method": "ping"},
        [1, 2],
        {"jsonrpc": "2.0", "id": 2, "method": "foo"},
        _call(3, "nope"),
        _call(4, "module", name="tpo"),
        _call(5, "module", name="top", unknown="x"),
        _call(6, "find", pattern="x"),
        _call(7, "module", name="top", summary=True),
    )
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["error"]["code"] == -32600
    assert responses[2]["error"]["code"] == -32600
    assert responses[3]["error"]["code"] == -32601
    assert responses[4]["error"]["code"] == -32602
    not_found = responses[5]["result"]
    assert not_found["isError"] is True
    assert not_found["structuredContent"]["error"]["suggestions"] == ["top"]
    assert responses[6]["result"]["structuredContent"]["error"]["code"] == "bad-argument"
    assert responses[7]["result"]["structuredContent"]["error"]["message"] == "ValueError: bug"
    assert responses[8]["result"]["structuredContent"]["result"]["name"] == "top"


def test_changed_files(tmp_path):
    """Changed Files Are Read Again, New Files On Reload."""
    server = Server(_project(tmp_path))
    first = server.project
    assert server.project is first
    (tmp_path / "sub.sv").write_text("module sub (input logic a, input logic b);\nendmodule\n")
    second = server.project
    assert second is not first
    assert len(second.resolve("sub").unit.ports) == 2
    (tmp_path / "new.sv").write_text("module new; endmodule\n")
    assert server.project is second
    response = server.handle(_call(1, "reload"))
    assert response["result"]["structuredContent"] == {"reloaded": True, "files": 3}
    (tmp_path / "sub.sv").unlink()
    assert server.project.resolve("sub") is None


def test_tools_schema():
    """Every Tool Has A Valid Input Schema."""
    for tool in TOOLS:
        assert tool["inputSchema"]["type"] == "object"
        assert set(tool["inputSchema"].get("required", ())) <= set(tool["inputSchema"]["properties"])


def test_annotations_and_checks(tmp_path):
    """Read-Only Tools, Arguments Checked Against The Schema, Server Blackboxes."""
    assert all(tool["annotations"]["readOnlyHint"] for tool in TOOLS)
    (tmp_path / "top.sv").write_text("module top;\n  bb u_bb ();\nendmodule\n")
    server = Server(lambda: Project.from_dir(tmp_path), blackboxes=("bb",))
    error = server.handle(_call(1, "hierarchy", top="top", depth=-1))["result"]
    assert error["isError"] is True
    assert error["structuredContent"]["error"]["code"] == "bad-argument"
    assert server.handle(_call(2, "hierarchy", depth="x"))["result"]["isError"] is True
    assert server.handle(_call(3, "diagnostics"))["result"]["structuredContent"]["total"] == 0


def test_elaborate_tool(tmp_path):
    """Elaborate And Evaluate As Tools."""
    (tmp_path / "top.sv").write_text("module top #(parameter W = 8) (input logic [W-1:0] a);\nendmodule\n")
    server = Server(lambda: Project.from_dir(tmp_path))
    answer = server.handle(_call(1, "elaborate", top="top", params={"W": 3}))["result"]["structuredContent"]
    assert answer["result"]["ports"]["a"]["value"] == 3
    answer = server.handle(_call(2, "evaluate", expr="W * 2", scope="top"))["result"]["structuredContent"]
    assert answer["result"]["value"] == 16
    assert server.handle(_call(3, "elaborate", top="top", params=[1]))["result"]["isError"] is True


def test_detail(tmp_path):
    """Compact Answers By Default, Full On Request."""
    (tmp_path / "top.sv").write_text("module top (input logic a, b, output logic y);\n  assign y = a;\nendmodule\n")
    load = lambda: Project.from_dir(tmp_path)  # noqa: E731
    compact, full, bad = (
        response["result"]["structuredContent"]
        for response in _session(
            load,
            _call(1, "module", name="top", fields=["ports"]),
            _call(2, "module", name="top", fields=["ports"], detail="full"),
            _call(3, "module", name="top", detail="none"),
        )
    )
    assert compact["result"]["ports"]["columns"] == [
        "id",
        "name",
        "direction",
        "ptype",
        "dtype",
        "dim",
        "dim_unpacked",
        "default",
        "ifdefs",
        "comment",
        "line",
    ]
    assert full["result"]["ports"][0]["id"] == "top.sv:top.a"
    assert bad["error"]["code"] == "bad-argument"
