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

"""MCP Server: The Queries As Tools.

A minimal implementation of the Model Context Protocol over standard input and output (JSON-RPC 2.0, one
message per line), without further dependencies. See [hdl_parser.query][] for the queries.
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from . import query
from .project import Project

LOGGER = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
"""Supported protocol versions, the latest first."""

_LIMIT = {"type": "integer", "minimum": 0, "description": "Number of entries of every list. Default 100. 0: no limit."}
_FIELDS = {"type": "array", "items": {"type": "string"}, "description": "Fields to be returned. All by default."}
_SUMMARY = {"type": "boolean", "description": "Names and counts only."}
_NAME = {"type": "string", "description": "Name or full identifier ('rtl/top.sv:top')."}
_PATH = {
    "type": "string",
    "description": "Instance path of a signal: top module, instance names (with generate labels), signal: "
    "'top.u_core.u_alu.result_o'. The index of a for generate block selects one iteration: 'top.g_st[1].data'.",
}
_PASSTHROUGH = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Cells which pass their inputs on to their outputs, i.e. wrappers of technology cells: "
    "'buf_wrap', or with ports for modules which are not defined: 'BUFX2:A->Y'.",
}
_TOP_PARAMS = {
    "type": "object",
    "additionalProperties": {"type": ["integer", "number", "string", "boolean"]},
    "description": "Values of the parameters of the top, by name. Defaults otherwise.",
}

TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "module",
        "description": "One module, interface or package: parameters, ports, instances, signals, types, ... "
        "with source locations. Start with summary=true, then ask for the fields needed.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": _NAME, "fields": _FIELDS, "limit": _LIMIT, "summary": _SUMMARY},
            "required": ["name"],
        },
    },
    {
        "name": "hierarchy",
        "description": "Instance tree below the module 'top'. Without 'top': the top modules of the design. "
        "Names have the labels of the generate blocks around: 'g_lane.u_sub'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "top": _NAME,
                "depth": {"type": "integer", "minimum": 0, "description": "Number of instance levels below the top."},
                "limit": {**_LIMIT, "description": "Number of nodes. Default 100. 0: no limit."},
                "fields": {
                    **_FIELDS,
                    "description": "Fields of every node: module, inst, definition, multiple, loc. All by default.",
                },
                "summary": {"type": "boolean", "description": "Every node has name and module only."},
                "leaves": {
                    "type": "boolean",
                    "description": "Without 'top': tops without instances too (mostly unused library cells).",
                },
                "text": {
                    "type": "boolean",
                    "description": "The tree as indented text 'name (module)', much smaller than JSON.",
                },
            },
        },
    },
    {
        "name": "where_used",
        "description": "All places a module or interface is instantiated at, with file and location. "
        "Works for modules which are not defined in the project (blackboxes, hard macros) too.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": _NAME, "limit": _LIMIT},
            "required": ["name"],
        },
    },
    {
        "name": "find",
        "description": "Items by name. Without wildcard: part of the name, not case sensitive. With wildcards "
        "(*, ?, [...]): the name or the full identifier ('rtl/top.sv:top.*').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(set(query.KINDS.values()))},
                    "description": "Kinds of items. All by default.",
                },
                "limit": _LIMIT,
                "fields": _FIELDS,
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "diagnostics",
        "description": "Problems found in the design: undefined modules, macros not expanded, files which cannot "
        "be read, ... with code, severity, message and location: 'file' and 'line' are where the problem is. "
        "A problem within an included file is reported once, 'parsed' lists the files including it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": list(query.SEVERITIES), "description": "Minimum severity."},
                "codes": {"type": "array", "items": {"type": "string"}},
                "file": {
                    "type": "string",
                    "description": "Path of a file, relative to the root, or a pattern: the problems located in it "
                    "or found by parsing it.",
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns of files whose problems are left out: 'lib/stdcells/*'. A problem "
                    "found by parsing other files too is kept for them.",
                },
                "blackboxes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns of module names known to be missing: no 'undefined-module' for them.",
                },
                "group_by": {
                    "type": "string",
                    "enum": ["code", "file", "module"],
                    "description": "Number of problems by group instead of the problems. Start with this.",
                },
                "limit": _LIMIT,
            },
        },
    },
    {
        "name": "elaborate",
        "description": "Values of the parameters and widths of the ports (in bits) of one instance, with the "
        "parameter values given down the hierarchy applied. Names are resolved across files and packages. "
        "Nothing is guessed: what is not known has 'unknown' with the reason. For generate loops with known "
        "indices, one node per iteration: 'g_lane[1].u_sub'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "top": _NAME,
                "path": {
                    "type": "string",
                    "description": "Instance names below the top, with generate labels: 'u_core.u_alu', "
                    "'g_lane[1].u_sub'.",
                },
                "params": {
                    "type": "object",
                    "additionalProperties": {"type": ["integer", "number", "string", "boolean"]},
                    "description": "Values of the parameters of the top, by name. Defaults otherwise.",
                },
                "depth": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Instance levels below the node returned too. Default 0: the node only.",
                },
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns of names of parameters and ports: 'WIDTH', '*_i'. All by default.",
                },
                "unknown": {"type": "boolean", "description": "Only values which are not known, with the reason."},
                "limit": {**_LIMIT, "description": "Number of nodes, and of parameters and ports of every node."},
            },
            "required": ["top"],
        },
    },
    {
        "name": "evaluate",
        "description": "Value of an expression ('$clog2(DEPTH)+1', 'pkg::WIDTH') within a module, interface or "
        "package.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expr": {"type": "string"},
                "scope": {**_NAME, "description": "Module, interface or package. Name or full identifier."},
                "params": {
                    "type": "object",
                    "additionalProperties": {"type": ["integer", "number", "string", "boolean"]},
                    "description": "Values of the parameters of the scope, by name. Defaults otherwise.",
                },
            },
            "required": ["expr", "scope"],
        },
    },
    {
        "name": "drivers",
        "description": "What drives a signal: assignments (with the signals they read and their conditions), "
        "output ports of instances, the connection of an input port within the parent. Ask for the drivers of "
        "the signals read ('nets') to go further. A select within a generate loop is evaluated per iteration "
        "('[4*i+:4]': one driver with '[3:0]', one with '[7:4]'). A select of the signal ('top.data[5]') keeps "
        "the drivers of its bits.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": _PATH, "params": _TOP_PARAMS, "limit": _LIMIT, "passthrough": _PASSTHROUGH},
            "required": ["path"],
        },
    },
    {
        "name": "loads",
        "description": "What a signal drives: assignments reading it (also by a condition: 'control'), input ports "
        "of instances, the connection of an output port within the parent. The 'select' of the driven signal is "
        "evaluated per iteration of a generate loop. A select of the signal ('top.data[5]') keeps the loads which "
        "may read its bits (an assignment is kept: the bits it reads are not known).",
        "inputSchema": {
            "type": "object",
            "properties": {"path": _PATH, "params": _TOP_PARAMS, "limit": _LIMIT, "passthrough": _PASSTHROUGH},
            "required": ["path"],
        },
    },
    {
        "name": "trace",
        "description": "Shortest connection from one signal to another one below the same top, hop by hop with "
        "kind and location, with 'counts' of hops, flip-flops and conditions. Stops behind flip-flops unless "
        "through_regs=true, and at undefined modules ('stopped_at'). Selects ('top.data[5]') restrict the "
        "start to the loads reading those bits, the end to the loads driving them.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "src": {**_PATH, "description": "Instance path of the signal to start at."},
                "dst": {**_PATH, "description": "Instance path of the signal to reach."},
                "params": _TOP_PARAMS,
                "through_regs": {"type": "boolean", "description": "Continue behind flip-flops."},
                "control": {
                    "type": "boolean",
                    "description": "Follow conditions, resets and clocks too. Default true.",
                },
                "limit": {**_LIMIT, "description": "Number of hops. Default 100. 0: no limit."},
                "passthrough": _PASSTHROUGH,
            },
            "required": ["src", "dst"],
        },
    },
    {
        "name": "reload",
        "description": "Read the project again, i.e. after files were added. Changed files are read again "
        "automatically.",
        "inputSchema": {"type": "object", "properties": {}},
    },
)

_DETAIL = {"type": "string", "enum": list(query.DETAILS), "description": "Default compact. See instructions."}

for _tool in TOOLS:
    _tool["annotations"] = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
    if _tool["name"] != "reload":
        _tool["inputSchema"]["properties"]["detail"] = _DETAIL

_QUERIES: dict[str, Callable[..., dict[str, Any]]] = {
    "module": query.module,
    "hierarchy": query.hierarchy,
    "where_used": query.where_used,
    "find": query.find,
    "diagnostics": query.diagnostics,
    "elaborate": query.elaborate,
    "evaluate": query.evaluate,
    "drivers": query.drivers,
    "loads": query.loads,
    "trace": query.trace,
}


class Server:
    """MCP Server on the project created by `load`."""

    def __init__(self, load: Callable[[], Project], project: Project | None = None, blackboxes: tuple[str, ...] = ()):
        self.load = load
        self.blackboxes = blackboxes
        self._project = project
        self._stamps = _stamps(project) if project is not None else {}

    @property
    def project(self) -> Project:
        """The project, read again if one of its files changed."""
        if self._project is None or self._stamps != _stamps(self._project):
            self.reload()
        return self._project  # type: ignore[return-value]

    def reload(self) -> None:
        """Read the project again."""
        self._project = self.load()
        self._stamps = _stamps(self._project)

    def handle(self, message: Any) -> dict[str, Any] | None:  # noqa: PLR0911
        """Answer to `message`. `None` for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
            return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")
        if "id" not in message:
            return None
        id_ = message["id"]
        method = message["method"]
        params = message.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return _result(
                id_,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "hdl-parser", "version": _version()},
                    "instructions": INSTRUCTIONS,
                },
            )
        if method == "ping":
            return _result(id_, {})
        if method == "tools/list":
            return _result(id_, {"tools": list(TOOLS)})
        if method == "tools/call":
            return self._call(id_, params)
        return _error(id_, -32601, f"Method not found: {method}")

    def _call(self, id_: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "reload":
            self.reload()
            return _result(id_, _content({"reloaded": True, "files": len(self.project.files)}))
        func = _QUERIES.get(name)  # type: ignore[arg-type]
        if func is None:
            return _error(id_, -32602, f"Unknown tool: {name}")
        tool = next(tool for tool in TOOLS if tool["name"] == name)
        unknown = sorted(set(arguments) - set(tool["inputSchema"]["properties"]))
        if unknown:
            return _result(id_, _content({"error": {"code": "bad-argument", "message": f"unknown: {unknown}"}}, True))
        if name == "diagnostics" and self.blackboxes:
            arguments = {**arguments, "blackboxes": (*self.blackboxes, *arguments.get("blackboxes", ()))}
        try:
            _check(tool["inputSchema"]["properties"], arguments)
            detail = arguments.pop("detail", "compact")
            answer = query.render(func(self.project, **arguments), detail)
        except query.QueryError as exc:
            return _result(id_, _content(exc.to_dict(), True))
        except Exception as exc:
            LOGGER.exception("tool %s failed", name)
            error = {"code": "failed", "message": f"{type(exc).__name__}: {exc}"}
            return _result(id_, _content({"error": error}, True))
        return _result(id_, _content(answer))


INSTRUCTIONS = """\
Questions about the SystemVerilog and VHDL design of this project. Every item has a full identifier \
'<file>:<id>' (i.e. 'rtl/top.sv:top.u_sub') and a source 'line'. Answers are compact: the identifier of an item \
within another one is left out, if it is the one around plus its name, and relative otherwise; a list of objects \
may be a table {columns, rows}. detail='full' gives every identifier and 'loc' with columns. \
Lists are limited: what is left out is counted in 'omitted'. Start small: 'hierarchy' without 'top' gives the top \
modules, the largest first, 'module' with summary=true the counts, 'find' locates items by name. 'diagnostics' \
with group_by='code' or 'file' tells what may be missing or wrong, then filter by code, file or exclude. \
'elaborate' gives the values of the parameters and the widths of the ports of an instance \
('path' below 'top'), 'evaluate' the value of an expression. 'drivers' and 'loads' tell what drives a signal \
and what it drives, by instance path ('top.u_core.result_o'), 'trace' the connection between two signals. \
Values which cannot be computed have 'unknown' with the reason: never take them as 0. Code under an unresolved \
`ifdef is tagged 'ifdefs' (see 'module' with fields 'assigns' or 'insts'); 'drivers' and 'trace' do not show it."""


def _check(properties: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Check `arguments` against the types and minimums of `properties`."""
    types: dict[str, Any] = {
        "integer": int,
        "boolean": bool,
        "string": str,
        "array": (list, tuple),
        "object": dict,
    }
    for key, value in arguments.items():
        schema = properties[key]
        expected = types.get(schema.get("type", ""))
        valid = expected is None or (isinstance(value, expected) and not (expected is int and isinstance(value, bool)))
        if not valid:
            raise query.QueryError("bad-argument", f"'{key}' must be of type {schema['type']}.")
        if "minimum" in schema and value < schema["minimum"]:
            raise query.QueryError("bad-argument", f"'{key}' must be at least {schema['minimum']}.")
        if "enum" in schema and value not in schema["enum"]:
            raise query.QueryError("bad-argument", f"'{key}' must be one of {schema['enum']}.", schema["enum"])


def serve(
    load: Callable[[], Project],
    stdin: TextIO,
    stdout: TextIO,
    project: Project | None = None,
    blackboxes: tuple[str, ...] = (),
) -> None:
    """Serve the project created by `load` until `stdin` ends. `project`: the one already created by `load`.

    `blackboxes`: Patterns of module names known to be missing, applied to every 'diagnostics' call.
    """
    server = Server(load, project, blackboxes)
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: dict[str, Any] | None = _error(None, -32700, "Parse error")
        else:
            response = server.handle(message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


def _stamps(project: Project) -> dict[Path, tuple[int, int] | None]:
    """Modification time and size of all files of `project` and the files they include."""
    stamps: dict[Path, tuple[int, int] | None] = {}
    for file in project.files:
        for path in (file.path, *file.includes):
            if path is None:
                continue
            full = project.root / path
            try:
                stat = full.stat()
                stamps[full] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                stamps[full] = None
    return stamps


def _content(answer: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(answer)}],
        "structuredContent": answer,
        "isError": is_error,
    }


def _result(id_: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415

    try:
        return version("hdl-parser")
    except PackageNotFoundError:  # pragma: no cover
        return "0"
