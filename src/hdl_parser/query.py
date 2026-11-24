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

"""Queries: Narrow Questions On A Project, With Small JSON Answers.

Every query takes a [Project][hdl_parser.project.Project] and returns a JSON compatible `dict`.
The same queries are the commands of the command line (`hdl-parser module ...`) and the tools of the
MCP server (`hdl-parser mcp`).

* [module][hdl_parser.query.module]: one module, interface or package.
* [hierarchy][hdl_parser.query.hierarchy]: the instance tree below a module, or the top modules.
* [where_used][hdl_parser.query.where_used]: all instances of a module.
* [find][hdl_parser.query.find]: items by name.
* [diagnostics][hdl_parser.query.diagnostics]: problems found.
* [elaborate][hdl_parser.query.elaborate]: values of the parameters and widths of the ports of an instance.
* [evaluate][hdl_parser.query.evaluate]: value of an expression within a module or package.
* [drivers][hdl_parser.query.drivers]: what drives a signal.
* [loads][hdl_parser.query.loads]: what a signal drives.
* [trace][hdl_parser.query.trace]: how one signal reaches another one.

Answers are sized for a context window:

* Every list is limited (`limit`, [DEFAULT_LIMIT][hdl_parser.query.DEFAULT_LIMIT] by default, `0` for no
  limit). What is left out is counted in `omitted`, so nothing is dropped silently.
* `fields` selects the fields of the items.
* `summary` gives names and counts only.

Every item has its full identifier (`rtl/top.sv:top.u_sub`), whose file part is the path of its file relative
to the root of the project, and its source location (`loc`). The command line and the MCP server hand the
answers to agents compact: see [render][hdl_parser.query.render]. An identifier can be handed over to `find`,
`module`, `hierarchy` and `where_used`.

A name which is not found raises [QueryError][hdl_parser.query.QueryError], with similar names as suggestions.
"""

import difflib
import json
import re
from collections.abc import Iterable
from fnmatch import fnmatchcase
from typing import Any

from . import datamodel as dm
from ._conn import Connectivity, Node, PathError, base_key
from .project import Definition, Project

DEFAULT_LIMIT = 100
"""Default number of entries of every list within an answer."""

KINDS: dict[type, str] = {
    dm.Interface: "interface",
    dm.Module: "module",
    dm.Package: "package",
    dm.Param: "param",
    dm.Port: "port",
    dm.Signal: "signal",
    dm.Process: "process",
    dm.Modport: "modport",
    dm.Function: "function",
    dm.Typedef: "typedef",
    dm.Member: "member",
    dm.ModuleInstance: "instance",
    dm.Connection: "connection",
    dm.MacroCall: "macro",
}
"""Kind of every item, as used by `find`."""

SEVERITIES = ("error", "warning", "info")
"""Severities, from the most severe."""

_ALWAYS = ("id", "kind", "name")
_WILDCARD = re.compile(r"[*?\[]")


class QueryError(Exception):
    """A Query Cannot Be Answered.

    Attributes:
        code: `not-found` (no such module or item) or `bad-argument`.
        message: Description.
        suggestions: Similar names, which exist.
    """

    def __init__(self, code: str, message: str, suggestions: Iterable[str] = ()):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestions = tuple(suggestions)

    def to_dict(self) -> dict[str, Any]:
        """JSON compatible answer."""
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.suggestions:
            error["suggestions"] = list(self.suggestions)
        return {"error": error}


# --- module ---


def module(
    project: Project, name: str, fields: Iterable[str] = (), limit: int | None = None, summary: bool = False
) -> dict[str, Any]:
    """One module, interface or package: everything extracted from it.

    Args:
        project: Project.
        name: Name or full identifier. A name stands for the definition used by instances.

    Keyword Args:
        fields: Fields of the module to be returned (`ports`, `params`, `insts`, ...). All by default.
                `id`, `kind` and `name` are always returned. `ports.direction` selects a field of the items of a
                list: their `id` and `name` are always returned.
        limit: Number of entries of every list (ports, instances, ...). The ones left out are counted
               in `omitted`, by field.
        summary: Lists are replaced by their number of entries (`counts`).

    The answer is `{"result": {...}}`. `others` lists further definitions of the same name, by identifier.
    `bodies` lists the VHDL architectures located in other files.
    """
    definitions = _definitions(project, name)
    used = definitions[0]
    unit = _unit_dict(used)
    if used.bodies:
        unit["bodies"] = [file.full_id(body) for file, body in used.bodies]
    names = tuple(fields)
    unit = _select(unit, [name.partition(".")[0] for name in names], _unit_fields(used.unit))
    unit = _select_items(unit, names)
    answer: dict[str, Any] = {"query": "module"}
    if summary:
        result = {key: value for key, value in unit.items() if not isinstance(value, list)}
        result["counts"] = {key: len(value) for key, value in unit.items() if isinstance(value, list)}
        answer["result"] = result
    else:
        omitted: dict[str, int] = {}
        for key, value in unit.items():
            if isinstance(value, list):
                unit[key], left = _limit(value, limit)
                if left:
                    omitted[key] = left
        answer["result"] = unit
        if omitted:
            answer["omitted"] = omitted
    if len(definitions) > 1:
        answer["others"] = [definition.id for definition in definitions[1:]]
    return answer


def _definitions(project: Project, name: str) -> tuple[Definition, ...]:
    if ":" in name:
        definition = project.resolve(name)
        item = project.find(name)
        if definition is None and isinstance(item, dm.Package):
            definition = next((found for found in project.definitions(item.name) if found.unit is item), None)
        if definition is None:
            raise QueryError("not-found", f"'{name}' is no module, interface or package.", _similar_ids(project, name))
        return (definition,)
    definitions = project.definitions(name)
    if not definitions:
        raise QueryError("not-found", f"'{name}' is not defined in the project.", _similar_units(project, name))
    return definitions


def _unit_dict(definition: Definition) -> dict[str, Any]:
    file = definition.file
    data = _item_dict(file, definition.unit)
    return {"id": data.pop("id"), "kind": data.pop("kind"), "name": data.pop("name"), **data}


def _unit_fields(unit: dm.Module | dm.Package) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*_ALWAYS, "file", "bodies", *type(unit).model_fields)))


# --- hierarchy ---


def hierarchy(  # noqa: PLR0913
    project: Project,
    top: str | None = None,
    depth: int | None = None,
    limit: int | None = None,
    fields: Iterable[str] = (),
    summary: bool = False,
    leaves: bool = False,
    text: bool = False,
) -> dict[str, Any]:
    """The instance tree below the module `top`, or the top modules, if `top` is not given.

    Args:
        project: Project.
        top: Name or full identifier of the module.

    Keyword Args:
        depth: Number of instance levels below the top. Everything by default.
        limit: Number of nodes. Further nodes are left out, their parent is marked by `truncated`, and they are
               counted in `omitted`.
        fields: Fields of every node (`module`, `inst`, `definition`, `multiple`, `loc`).
                `name`, `children` and `truncated` are always returned.
        summary: Every node has `name` and `module` only.
        leaves: Top modules without instances are returned too. They are left out by default and counted in
                `leaves`, as they are mostly unused library cells, unless no top has instances.
        text: The tree as indented text (`tree`), one line per node: `<name> (<module>)`. Much smaller than JSON.

    The top modules are sorted by their number of instances (`insts`, all levels), the largest first.
    `library` marks a top found through a library option of a filelist.

    A node of a module which is not defined in the project has no `definition`. Its `loc` is the location of
    the instance.
    """
    if depth is not None and depth < 0:
        raise QueryError("bad-argument", "depth must not be negative.")
    if top is None:
        return _tops(project, limit, leaves)
    node = project.hierarchy(top, depth=depth)
    if node is None:
        raise QueryError("not-found", f"'{top}' is no module of the project.", _similar_units(project, top))
    names = ("name", "module") if summary or text else tuple(fields)
    budget = [_resolve_limit(limit)]
    left_out = [0]
    tree = _node(project, node, names, budget, left_out)
    answer: dict[str, Any] = {"query": "hierarchy"}
    if text:
        answer["tree"] = "\n".join(_lines(tree, 0))
    else:
        answer["result"] = tree
    if left_out[0]:
        answer["omitted"] = left_out[0]
    return answer


def _tops(project: Project, limit: int | None, leaves: bool) -> dict[str, Any]:
    counts: dict[str, int] = {}

    def count(definition: Definition, path: tuple[str, ...]) -> int:
        if definition.id in counts:
            return counts[definition.id]
        number = 0
        for file, inst in definition.insts:
            number += 1
            child = project._resolve_inst(file, inst)
            if child is not None and child.id not in path:
                number += count(child, (*path, child.id))
        counts[definition.id] = number
        return number

    sizes = [(definition, count(definition, (definition.id,))) for definition in project.tops()]
    # a design of leaves only: all of them
    leaves = leaves or not any(insts for _, insts in sizes)
    tops = []
    left_out = 0
    for definition, insts in sizes:
        if not insts and not leaves:
            left_out += 1
            continue
        entry = {**_brief(definition.file, definition.unit), "insts": insts}
        if definition.file.file_id in project.libraries:
            entry["library"] = True
        tops.append(entry)
    tops.sort(key=lambda entry: -entry["insts"])
    result, omitted = _limit(tops, limit)
    answer = _list_answer("hierarchy", result, len(tops), omitted)
    if left_out:
        answer["leaves"] = left_out
    return answer


def _lines(node: dict[str, Any], level: int) -> Iterable[str]:
    indent = "  " * level
    module = node.get("module", "")
    line = f"{indent}{node['name']}" if module == node["name"] else f"{indent}{node['name']} ({module})"
    if node.get("truncated"):
        line += " ..."
    yield line
    for child in node.get("children", ()):
        yield from _lines(child, level + 1)


_NODE_FIELDS = ("name", "module", "inst", "definition", "multiple", "loc", "children", "truncated")


def _node(
    project: Project, node: dm.HierarchyNode, names: tuple[str, ...], budget: list[int | None], omitted: list[int]
) -> dict[str, Any]:
    data: dict[str, Any] = node.model_dump(mode="json", exclude_defaults=True, exclude={"children", "params", "ports"})
    item = project.find(node.inst) if node.inst else project.find(node.definition)
    loc: dm.Location | None = getattr(item, "loc", None)
    if loc is not None:
        data["loc"] = loc.model_dump(mode="json", exclude_defaults=True)
    if names:
        unknown = sorted(set(names) - set(_NODE_FIELDS))
        if unknown:
            raise QueryError("bad-argument", f"unknown fields: {', '.join(unknown)}.", _NODE_FIELDS)
        data = {key: value for key, value in data.items() if key in (*names, "name", "truncated")}
    children = []
    for child in node.children:
        if budget[0] is not None and budget[0] <= 0:
            omitted[0] += _count(child)
            data["truncated"] = True
            continue
        if budget[0] is not None:
            budget[0] -= 1
        children.append(_node(project, child, names, budget, omitted))
    if children:
        data["children"] = children
    return data


def _count(node: dm.HierarchyNode) -> int:
    return 1 + sum(_count(child) for child in node.children)


# --- where-used ---


def where_used(project: Project, name: str, limit: int | None = None) -> dict[str, Any]:
    """All places the module or interface `name` (a name or full identifier) is instantiated at.

    Every entry has the full identifier of the instance (`inst`), the module it is located in (`module`),
    its file and location. `module` of the answer is the identifier of the definition, which is used.

    A module which is not defined in the project (a blackbox, a hard macro, a cell) is found by the module
    name of its instances. `module` of the answer is missing then and `defined` is `false`.
    """
    definition = project.resolve(name) or project.resolve(name, casefold=True)
    if definition is None:
        undefined = [
            (file, inst)
            for file, inst in project._undefined
            if inst.module == name or (file.lang == "vhdl" and inst.module.lower() == name.lower())
        ]
        if not undefined:
            names = (*(unit.name for _, unit in _units(project)), *(inst.module for _, inst in project._undefined))
            raise QueryError("not-found", f"'{name}' is neither defined nor instantiated.", _similar(name, names))
        uses = [
            {
                "inst": file.full_id(inst),
                "module": _parent_id(file.full_id(inst)),
                "file": file.file_id,
                **_loc(inst.loc),
            }
            for file, inst in undefined
        ]
        result, omitted = _limit(uses, limit)
        return {**_list_answer("where-used", result, len(uses), omitted), "defined": False}
    uses = [
        {"inst": use.inst, "module": use.module, "file": _file_of(use.inst), **_loc(use.loc)}
        for use in project.where_used(definition.id)
    ]
    result, omitted = _limit(uses, limit)
    return {**_list_answer("where-used", result, len(uses), omitted), "module": definition.id}


def _parent_id(full_id: str) -> str:
    file_id, _, item_id = full_id.rpartition(":")
    return f"{file_id}:{item_id.split('.', 1)[0]}"


# --- find ---


def find(
    project: Project,
    pattern: str,
    kinds: Iterable[str] = (),
    limit: int | None = None,
    fields: Iterable[str] = (),
) -> dict[str, Any]:
    """Items by name, in the order of the files.

    Args:
        project: Project.
        pattern: Without wildcard: part of the name, not case sensitive (`clk` finds `clk_i`).
                 With wildcards (`*`, `?`, `[...]`): the name or the full identifier
                 (`*_i`, `rtl/top.sv:top.*`).

    Keyword Args:
        kinds: Kinds of items to be found: `module`, `port`, `instance`, ... (see [KINDS][hdl_parser.query.KINDS]).
               All by default.
        limit: Number of items.
        fields: Fields of every item. By default `id`, `kind`, `name`, `file`, `loc` and the
                fields which are no lists (i.e. `direction`, `ptype` and `dim` of a port).
    """
    wanted = set(kinds)
    unknown = sorted(wanted - set(KINDS.values()))
    if unknown:
        raise QueryError("bad-argument", f"unknown kinds: {', '.join(unknown)}.", sorted(set(KINDS.values())))
    if _WILDCARD.search(pattern):

        def match(file: dm.File, item: dm.Item) -> bool:
            name = getattr(item, "name", "")
            return fnmatchcase(name, pattern) or fnmatchcase(file.full_id(item), pattern)
    else:
        lower = pattern.lower()

        def match(file: dm.File, item: dm.Item) -> bool:  # noqa: ARG001
            return lower in getattr(item, "name", "").lower()

    found = [
        _select(_brief(file, item), fields, None)
        for file in project.files
        for item in file.iter_items()
        if (not wanted or _kind(item) in wanted) and match(file, item)
    ]
    result, omitted = _limit(found, limit)
    return _list_answer("find", result, len(found), omitted)


# --- diagnostics ---


def diagnostics(  # noqa: C901, PLR0912, PLR0913
    project: Project,
    severity: str | None = None,
    codes: Iterable[str] = (),
    file: str | None = None,
    limit: int | None = None,
    exclude: Iterable[str] = (),
    blackboxes: Iterable[str] = (),
    group_by: str | None = None,
) -> dict[str, Any]:
    """Problems found in the project, in the order of the files.

    Every problem is located where it is: `file` and `loc` (`line`). A problem within an included file is found
    by parsing the files including it: they are listed in `parsed`. It is reported once.

    Args:
        project: Project.

    Keyword Args:
        severity: Minimum severity: `error`, `warning` or `info` (everything, the default).
        codes: Codes to be returned (`undefined-module`, ...). All by default.
        file: Path of a file, or a pattern on the paths (`rtl/*`): the problems located in it, or found by parsing
              it. All files by default.
        limit: Number of problems.
        exclude: Patterns on the paths of files, whose problems are left out (`lib/stdcells/*`): the problems located
                 in them, or found by parsing them only.
        blackboxes: Patterns on module names, which are known not to be part of the project (blackboxes,
                    hard macros, cells): their `undefined-module` problems are left out.
        group_by: `code`, `file` or `module` (the undefined module): the number of problems by group,
                  the largest first, instead of the problems.

    `counts` has the number of problems by severity, with the filters applied.
    """
    if severity is not None and severity not in SEVERITIES:
        raise QueryError("bad-argument", f"unknown severity '{severity}'.", SEVERITIES)
    if group_by is not None and group_by not in _GROUPS:
        raise QueryError("bad-argument", f"unknown group '{group_by}'.", _GROUPS)
    located = {diagnostic.file for _, diagnostic in project.iter_diagnostics() if diagnostic.file}
    if file is not None and not _WILDCARD.search(file) and file not in located:
        found_file = project.file(file)
        if found_file is None:
            raise QueryError("not-found", f"'{file}' is no file of the project.", _similar_files(project, file))
        file = found_file.file_id
    allowed = SEVERITIES[: SEVERITIES.index(severity) + 1] if severity else SEVERITIES
    wanted = set(codes)
    excluded = tuple(exclude)
    boxes = tuple(blackboxes)
    modules = {file.full_id(inst): inst.module for file, inst in project._undefined} if boxes or group_by else {}
    found: list[dict[str, Any]] = []
    # problems within an included file, by location: found once, by several files
    shared: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for file_id, diagnostic in project.iter_diagnostics():
        if diagnostic.severity not in allowed or (wanted and diagnostic.code not in wanted):
            continue
        # the file the problem is located in, and the parsed file, if it is another one
        paths = (diagnostic.file or file_id, file_id) if file_id else (diagnostic.file,)
        if file is not None and not any(fnmatchcase(path, file) for path in paths):
            continue
        if any(fnmatchcase(path, pattern) for path in paths for pattern in excluded):
            continue
        module_name = modules.get(f"{file_id}:{diagnostic.item}") if diagnostic.code == "undefined-module" else None
        if module_name and any(fnmatchcase(module_name, pattern) for pattern in boxes):
            continue
        data = _diagnostic_entry(file_id, diagnostic, shared)
        if data is None:
            continue
        if group_by == "module":
            data["module"] = module_name
        found.append(data)
    counts = {name: sum(entry["severity"] == name for entry in found) for name in SEVERITIES}
    if group_by is not None:
        groups: dict[str, int] = {}
        for entry in found:
            key = entry.get(group_by)
            if key is not None:
                groups[key] = groups.get(key, 0) + 1
        ordered = [{group_by: key, "count": number} for key, number in sorted(groups.items(), key=lambda kv: -kv[1])]
        result, omitted = _limit(ordered, limit)
        answer = _list_answer("diagnostics", result, len(ordered), omitted)
    else:
        result, omitted = _limit(found, limit)
        answer = _list_answer("diagnostics", result, len(found), omitted)
    answer["counts"] = counts
    return answer


_GROUPS = ("code", "file", "module")


def _diagnostic_entry(
    file_id: str, diagnostic: dm.Diagnostic, shared: dict[tuple[str, str, str, str], dict[str, Any]]
) -> dict[str, Any] | None:
    """Entry of `diagnostic` of the file `file_id` (empty for the project): located where the problem is.

    A problem within an included file is added to `parsed` of the entry in `shared`, if it has been found before.
    Then the result is `None`.
    """
    data = diagnostic.model_dump(mode="json", exclude_defaults=True)
    if file_id and "item" in data:
        data["item"] = f"{file_id}:{data['item']}"
    where = diagnostic.file or file_id
    data = {"file": where, **{key: value for key, value in data.items() if key != "file"}}
    if file_id and diagnostic.file:
        key = (diagnostic.code, where, str(diagnostic.loc), diagnostic.message)
        if key in shared:
            shared[key]["parsed"].append(file_id)
            return None
        data["parsed"] = [file_id]
        shared[key] = data
    return data


# --- elaborate ---


def elaborate(  # noqa: PLR0913
    project: Project,
    top: str,
    path: str = "",
    params: dict[str, int | float | str | bool] | None = None,
    depth: int = 0,
    names: Iterable[str] = (),
    unknown: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Values of the parameters and widths of the ports of the instance `path` below the module `top`.

    Args:
        project: Project.
        top: Name or full identifier of the top module.

    Keyword Args:
        path: Instance names below `top`, separated by dots, with the labels of the generate blocks around:
              `u_core.u_alu`, `g_st[1].u_sub`. The top itself by default.
        params: Values of the parameters of the top, by name. Its defaults are used otherwise.
        depth: Number of instance levels below the node, which are returned too. Default 0: the node only.
        names: Patterns of the names of the parameters and ports to be returned. All by default.
        unknown: Only parameters and ports whose value is not known, with the reason.
        limit: Number of nodes, and number of parameters and of ports of every node.

    Every value has the expression as written (`expr`) and its `value`, or the reason why it is not known
    (`unknown`). For a port, `value` is its number of bits. Nothing is guessed.
    """
    if depth < 0:
        raise QueryError("bad-argument", "depth must not be negative.")
    steps = [step for step in path.split(".") if step]
    try:
        node = project.elaborate(top, params=params, depth=len(steps) + depth)
    except (TypeError, ValueError) as exc:
        raise QueryError("bad-argument", str(exc)) from exc
    if node is None:
        raise QueryError("not-found", f"'{top}' is no module of the project.", _similar_units(project, top))
    index = 0
    while index < len(steps):
        # the name of a child may span steps: `g_st[1].u_sub`
        found = next(
            (
                (end, child)
                for end in range(len(steps), index, -1)
                for child in node.children
                if child.name == ".".join(steps[index:end])
            ),
            None,
        )
        if found is None:
            where = ".".join(steps[:index]) or top
            wanted = ".".join(steps[index:])
            choices = [child.name for child in node.children]
            # the iterations of an unrolled loop first: `g[0].u`, `g[1].u` for `g.u`
            same = [name for name in choices if base_key(name) == base_key(wanted)]
            raise QueryError(
                "not-found", f"'{where}' has no instance '{wanted}'.", same or _similar(wanted, choices) or choices
            )
        index, node = found
    patterns = tuple(names)
    budget = [_resolve_limit(limit)]
    omitted: dict[str, int] = {}
    answer: dict[str, Any] = {
        "query": "elaborate",
        "result": _elab_node(node, patterns, unknown, limit, budget, omitted),
    }
    if omitted:
        answer["omitted"] = omitted
    return answer


def _elab_node(  # noqa: PLR0913
    node: dm.HierarchyNode,
    patterns: tuple[str, ...],
    unknown: bool,
    limit: int | None,
    budget: list[int | None],
    omitted: dict[str, int],
) -> dict[str, Any]:
    data: dict[str, Any] = node.model_dump(
        mode="json", exclude_defaults=True, exclude={"children", "params", "ports", "truncated"}
    )
    if not node.definition:
        data["unknown"] = f"module '{node.module}' is not defined in the project"
    for key in ("params", "ports"):
        values = [
            (name, value.model_dump(mode="json", exclude_defaults=True))
            for name, value in getattr(node, key).items()
            if (not patterns or any(fnmatchcase(name, pattern) for pattern in patterns))
            and (not unknown or value.value is None)
        ]
        kept, left = _limit(values, limit)
        if kept:
            data[key] = dict(kept)
        if left:
            omitted[key] = omitted.get(key, 0) + left
    children = []
    truncated = node.truncated
    for child in node.children:
        if budget[0] is not None and budget[0] <= 0:
            omitted["nodes"] = omitted.get("nodes", 0) + 1
            truncated = True
            continue
        if budget[0] is not None:
            budget[0] -= 1
        children.append(_elab_node(child, patterns, unknown, limit, budget, omitted))
    if children:
        data["children"] = children
    if truncated:
        data["truncated"] = True
    return data


def evaluate(
    project: Project, expr: str, scope: str, params: dict[str, int | float | str | bool] | None = None
) -> dict[str, Any]:
    """Value of the expression `expr` within the module, interface or package `scope` (a name or full identifier).

    `params`: Values of the parameters of `scope`, by name. Its defaults are used otherwise.
    The answer has `value`, or the reason why it is not known (`unknown`).
    """
    if not (project.definitions(scope) or (":" in scope and project.find(scope) is not None)):
        raise QueryError("not-found", f"'{scope}' is not defined in the project.", _similar_units(project, scope))
    value = project.evaluate(expr, scope, params=params)
    return {"query": "evaluate", "result": value.model_dump(mode="json", exclude_defaults=True)}


# --- connectivity ---


def drivers(
    project: Project,
    path: str,
    params: dict[str, int | float | str | bool] | None = None,
    limit: int | None = None,
    passthrough: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """What drives the signal with the instance path `path`: `top.u_core.u_alu.result_o`.

    Args:
        project: Project.
        path: The top module (name or full identifier), the instance names below (with the labels of the generate
              blocks around) and the signal, separated by dots. The index of a `for` generate block selects one
              iteration (`top.g_st[1].data`), all of them without (`multiple`). A select of the signal
              (`top.data[5]`) keeps the drivers which may drive one of its bits.

    Keyword Args:
        params: Values of the parameters of the top, by name. Its defaults are used otherwise.
        limit: Number of drivers.
        passthrough: Cells which pass their inputs on to their outputs: `buf_wrap`, `BUFX2:A->Y`.

    `net` describes the signal: its `path`, `kind` (`port`, `signal`, `variable` of a process, `implicit`),
    `direction`, identifier and location. Every driver has its `kind` (`assign`, `comb`, `ff`, `latch`, `inst`,
    `port`, `unknown`), the signals it reads (`nets`), the ones read by its conditions (`conds`), the process,
    instance or module (`item`) and the location. The `select` of a driver within a `for` generate is evaluated
    per iteration (`[4*i+:4]` gives one driver with `[3:0]` and one with `[7:4]`). Ask for the drivers of `nets` to
    go further.
    See [Link][hdl_parser.datamodel.Link].
    """
    conn, node = _locate(project, path, params, passthrough=passthrough)
    select = conn.path_select(path)
    links = [conn.link(node, step, driver=True) for step in conn.drivers(node, conn.select_bits(node, select))]
    return _links("drivers", conn, node, links, limit, select)


def loads(
    project: Project,
    path: str,
    params: dict[str, int | float | str | bool] | None = None,
    limit: int | None = None,
    passthrough: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """What the signal with the instance path `path` drives. See [drivers][hdl_parser.query.drivers].

    Every load has the signals it drives (`nets`), with the `select` of the driven one. `control` marks a load,
    which reads the signal by a condition or as clock only. A select of the signal (`top.data[5]`) keeps the loads
    which may read one of its bits: an assignment reads the whole signal, as far as known.
    """
    conn, node = _locate(project, path, params, passthrough=passthrough)
    select = conn.path_select(path)
    links = [conn.link(node, step, driver=False) for step in conn.loads(node, conn.select_bits(node, select))]
    return _links("loads", conn, node, links, limit, select)


def trace(  # noqa: PLR0913
    project: Project,
    src: str,
    dst: str,
    params: dict[str, int | float | str | bool] | None = None,
    through_regs: bool = False,
    control: bool = True,
    limit: int | None = None,
    passthrough: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Shortest connection from the signal `src` to the signal `dst`: instance paths below the same top.

    Args:
        project: Project.
        src: Instance path of the signal to start at. See [drivers][hdl_parser.query.drivers].
        dst: Instance path of the signal to reach.

    Keyword Args:
        params: Values of the parameters of the top, by name. Its defaults are used otherwise.
        through_regs: Continue behind flip-flops. The search stops there by default.
        control: Follow conditions (`if`, `case`, `?:`), resets and clocks too. Data only otherwise.
        limit: Number of hops.
        passthrough: Cells which pass their inputs on to their outputs: `buf_wrap`, `BUFX2:A->Y`.

    The answer has `found`, and the hops from `src` to `dst`: every hop is a signal with the load reaching it
    (`kind`, `item`, location, the `select` driven). A select of `src` or `dst` (`top.data[5]`) restricts the
    start to the loads reading one of its bits, and the end to the loads driving one of them. `counts` tells the
    number of `hops`, the ones by flip-flops (`ff`) and the ones by conditions (`control`): a path with many of
    these is a weak connection. The search stops at modules which are not defined (blackboxes): `stopped_at`
    names them, if there is no connection.
    """
    conn, source = _locate(project, src, params, passthrough=passthrough)
    _, target = _locate(project, dst, params, conn)
    if _top(source[0]) is not _top(target[0]):
        raise QueryError("bad-argument", "'src' and 'dst' must be located below the same top.")
    src_bits = conn.select_bits(source, conn.path_select(src))
    dst_bits = conn.select_bits(target, conn.path_select(dst))
    found = conn.hops(conn.trace(source, target, through_regs, control, src_bits, dst_bits))
    hops = [_dump(hop) for hop in found]
    result, omitted = _limit(hops, limit)
    answer = _list_answer("trace", result, len(hops), omitted)
    answer["found"] = bool(hops)
    if hops:
        answer["counts"] = {
            "hops": len(found) - 1,
            "ff": sum(hop.kind == "ff" for hop in found),
            "control": sum(hop.control for hop in found),
        }
    else:
        stops = []
        if conn.ff_stops and not through_regs:
            stops.append(f"behind {conn.ff_stops} flip-flops (see 'through_regs')")
        stopped = conn.stopped()
        if stopped:
            stops.append(f"at {len(stopped)} modules which are not defined (see 'stopped_at', 'passthrough')")
        where = " and ".join(stops) or "with all loads followed"
        answer["hint"] = f"No connection. The search follows loads: it stopped {where}."
        if stopped:
            answer["stopped_at"] = stopped
    return answer


def _top(inst: Any) -> Any:
    while inst.parent is not None:
        inst = inst.parent
    return inst


def _locate(
    project: Project,
    path: str,
    params: dict[str, int | float | str | bool] | None,
    conn: Connectivity | None = None,
    passthrough: list[str] | tuple[str, ...] = (),
) -> tuple[Connectivity, Node]:
    try:
        conn = conn or project._connectivity(params, passthrough)
        return conn, conn.locate(path)
    except PathError as exc:
        raise QueryError("not-found", exc.message, exc.suggestions) from exc
    except (TypeError, ValueError) as exc:
        raise QueryError("bad-argument", str(exc)) from exc


def _links(  # noqa: PLR0913
    query: str, conn: Connectivity, node: Node, links: list[dm.Link], limit: int | None, select: str = ""
) -> dict[str, Any]:
    entries = [_dump(link) for link in links]
    result, omitted = _limit(entries, limit)
    net = conn.net(node)
    info: dict[str, Any] = {"path": conn.path(node), "kind": net.kind}
    if select:
        info["select"] = select
    if net.direction:
        info["direction"] = net.direction
    if net.item is not None and net.file is not None:
        info["id"] = net.file.full_id(net.item)
        info["file"] = net.file.file_id
        info.update(_loc(net.item.loc))
    if conn.multiple(node):
        info["multiple"] = True
    return {"query": query, "net": info, **_list_answer(query, result, len(entries), omitted)}


def _dump(model: dm.Link | dm.Hop) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_defaults=True)


# --- rendering ---


DETAILS = ("compact", "full")
"""Detail of the rendered answers: see [render][hdl_parser.query.render]."""


def render(answer: dict[str, Any], detail: str = "compact") -> dict[str, Any]:
    """The answer of a query, as returned to an agent: `compact` by default, `full` as is.

    `compact` gives the same information with fewer tokens:

    * A source location is its first line: `"line": 12` instead of `"loc": {...}`.
    * The identifier of an item within another one is left out, if it is the one of the item around followed by
      its name (`top.sv:top.clk` within `top.sv:top`), and relative otherwise (`#always1`).
    * A list of objects is a table, if that is smaller: `{"columns": [...], "rows": [[...], ...]}`. A field which
      an item has not, is `null`.
    """
    if detail not in DETAILS:
        raise QueryError("bad-argument", f"detail must be one of: {', '.join(DETAILS)}.")
    if detail == "full":
        return answer
    return _compact(answer, "")


def _compact(data: Any, parent: str) -> Any:
    if isinstance(data, list):
        items = [_compact(value, parent) for value in data]
        return _table(items) if len(items) > 1 and all(isinstance(item, dict) for item in items) else items
    if not isinstance(data, dict):
        return data
    result: dict[str, Any] = {}
    full_id = data.get("id") if isinstance(data.get("id"), str) else None
    for key, value in data.items():
        if key == "id" and full_id is not None and parent and full_id.startswith(f"{parent}."):
            relative = full_id[len(parent) + 1 :]
            if relative != data.get("name"):
                result["id"] = relative
        elif key == "loc" and isinstance(value, dict) and "line" not in data:
            result["line"] = value.get("line")
        else:
            result[key] = _compact(value, full_id or parent)
    return result


def _table(items: list[dict[str, Any]]) -> Any:
    """`items` as table, if that is smaller."""
    keys = dict.fromkeys(key for item in items for key in item)
    columns = [key for key in ("id", "name") if key in keys] + [key for key in keys if key not in ("id", "name")]
    table = {"columns": columns, "rows": [[item.get(column) for column in columns] for item in items]}
    size = len(json.dumps(table, separators=(",", ":")))
    return table if size < len(json.dumps(items, separators=(",", ":"))) else items


# --- helpers ---


def _kind(item: dm.Item) -> str:
    return KINDS[type(item)]


def _item_dict(file: dm.File, item: dm.Item) -> dict[str, Any]:
    """`item` as JSON compatible dictionary, with full identifiers."""
    data = _full_ids(file, item.model_dump(mode="json", exclude_defaults=True))
    return {"id": data.pop("id"), "kind": _kind(item), "file": file.file_id, **data}


def _full_ids(file: dm.File, data: Any) -> Any:
    if isinstance(data, dict):
        return {key: file.full_id(value) if key == "id" else _full_ids(file, value) for key, value in data.items()}
    if isinstance(data, list):
        return [_full_ids(file, value) for value in data]
    return data


def _brief(file: dm.File, item: dm.Item) -> dict[str, Any]:
    """Identifier, kind, name, file, location and the fields which are no lists."""
    data = _item_dict(file, item)
    return {key: value for key, value in data.items() if not isinstance(value, list | dict) or key == "loc"}


def _loc(loc: dm.Location | None) -> dict[str, Any]:
    return {"loc": loc.model_dump(mode="json", exclude_defaults=True)} if loc else {}


def _file_of(full_id: str) -> str:
    return full_id.rsplit(":", 1)[0]


def _select(data: dict[str, Any], fields: Iterable[str], valid: tuple[str, ...] | None) -> dict[str, Any]:
    names = tuple(fields)
    if not names:
        return data
    if valid is not None:
        unknown = sorted(set(names) - set(valid))
        if unknown:
            raise QueryError("bad-argument", f"unknown fields: {', '.join(unknown)}.", valid)
    return {key: value for key, value in data.items() if key in names or key in _ALWAYS}


def _select_items(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """`data` with the fields `list.field` of the items of its lists only."""
    by_list: dict[str, set[str]] = {}
    for name in fields:
        key, _, field = name.partition(".")
        if field:
            by_list.setdefault(key, set()).add(field)
    for key, keep in by_list.items():
        if not isinstance(data.get(key), list):
            raise QueryError("bad-argument", f"'{key}' is no list: '{key}.<field>' cannot be selected.")
        if any(name == key for name in fields):
            # the whole items are asked for, too
            continue
        wanted = keep | {"id", "name"}
        data[key] = [{field: value for field, value in item.items() if field in wanted} for item in data[key]]
    return data


def _resolve_limit(limit: int | None) -> int | None:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 0:
        raise QueryError("bad-argument", "limit must not be negative.")
    return limit or None


def _limit(items: list[Any], limit: int | None) -> tuple[list[Any], int]:
    number = _resolve_limit(limit)
    if number is None or len(items) <= number:
        return items, 0
    return items[:number], len(items) - number


def _list_answer(query: str, result: list[Any], total: int, omitted: int) -> dict[str, Any]:
    answer: dict[str, Any] = {"query": query, "result": result, "total": total}
    if omitted:
        answer["omitted"] = omitted
    return answer


def _similar(name: str, names: Iterable[str]) -> list[str]:
    choices = sorted(set(names))
    found = difflib.get_close_matches(name, choices, n=5, cutoff=0.6)
    lower = name.lower()
    if len(lower) >= 3:  # noqa: PLR2004
        found += [choice for choice in choices if lower in choice.lower() and choice not in found]
    return found[:5]


def _units(project: Project) -> Iterable[tuple[dm.File, dm.Module | dm.Package]]:
    for file in project.files:
        units: tuple[dm.Module | dm.Package, ...] = (*file.modules, *file.interfaces, *file.packages)
        for unit in units:
            yield file, unit


def _similar_units(project: Project, name: str) -> list[str]:
    return _similar(name.rsplit(":", 1)[-1], (unit.name for _, unit in _units(project)))


def _similar_ids(project: Project, full_id: str) -> list[str]:
    return _similar(full_id, (file.full_id(unit) for file, unit in _units(project)))


def _similar_files(project: Project, path: str) -> list[str]:
    return _similar(path, (file.file_id for file in project.files))
