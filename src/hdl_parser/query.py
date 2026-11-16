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

Answers are sized for a context window:

* Every list is limited (`limit`, [DEFAULT_LIMIT][hdl_parser.query.DEFAULT_LIMIT] by default, `0` for no
  limit). What is left out is counted in `omitted`, so nothing is dropped silently.
* `fields` selects the fields of the items.
* `summary` gives names and counts only.

Every item has its full identifier (`rtl/top.sv:top.u_sub`), whose file part is the path of its file relative
to the root of the project, and its source location (`loc`). An identifier can be handed over to `find`,
`module`, `hierarchy` and `where_used`.

A name which is not found raises [QueryError][hdl_parser.query.QueryError], with similar names as suggestions.
"""

import difflib
import re
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from . import datamodel as dm
from .project import Definition, Project, _relative

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
                `id`, `kind` and `name` are always returned.
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
    unit = _select(unit, fields, _unit_fields(used.unit))
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
    return (*_ALWAYS, "file", "bodies", *type(unit).model_fields)


# --- hierarchy ---


def hierarchy(  # noqa: PLR0913
    project: Project,
    top: str | None = None,
    depth: int | None = None,
    limit: int | None = None,
    fields: Iterable[str] = (),
    summary: bool = False,
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

    A node of a module which is not defined in the project has no `definition`. Its `loc` is the location of
    the instance.
    """
    if top is None:
        tops = [_brief(definition.file, definition.unit) for definition in project.tops()]
        result, omitted = _limit(tops, limit)
        return _list_answer("hierarchy", result, len(tops), omitted)
    node = project.hierarchy(top, depth=depth)
    if node is None:
        raise QueryError("not-found", f"'{top}' is no module of the project.", _similar_units(project, top))
    names = ("name", "module") if summary else tuple(fields)
    budget = [_resolve_limit(limit)]
    left_out = [0]
    answer: dict[str, Any] = {"query": "hierarchy", "result": _node(project, node, names, budget, left_out)}
    if left_out[0]:
        answer["omitted"] = left_out[0]
    return answer


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
    """
    definition = project.resolve(name) or project.resolve(name, casefold=True)
    if definition is None:
        raise QueryError("not-found", f"'{name}' is no module of the project.", _similar_units(project, name))
    uses = [
        {"inst": use.inst, "module": use.module, "file": _file_of(use.inst), **_loc(use.loc)}
        for use in project.where_used(definition.id)
    ]
    result, omitted = _limit(uses, limit)
    return {**_list_answer("where-used", result, len(uses), omitted), "module": definition.id}


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


def diagnostics(
    project: Project,
    severity: str | None = None,
    codes: Iterable[str] = (),
    file: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Problems found in the project, in the order of the files.

    Args:
        project: Project.

    Keyword Args:
        severity: Minimum severity: `error`, `warning` or `info` (everything, the default).
        codes: Codes to be returned (`undefined-module`, ...). All by default.
        file: Path of a file. All files by default.
        limit: Number of problems.

    `counts` has the number of problems by severity, with the filters applied.
    """
    if severity is not None and severity not in SEVERITIES:
        raise QueryError("bad-argument", f"unknown severity '{severity}'.", SEVERITIES)
    if file is not None and project.file(file) is None:
        raise QueryError("not-found", f"'{file}' is no file of the project.", _similar_files(project, file))
    allowed = SEVERITIES[: SEVERITIES.index(severity) + 1] if severity else SEVERITIES
    wanted = set(codes)
    found = []
    for file_id, diagnostic in project.iter_diagnostics():
        if diagnostic.severity not in allowed or (wanted and diagnostic.code not in wanted):
            continue
        if file is not None and file_id != project.file(file).file_id:  # type: ignore[union-attr]
            continue
        data = diagnostic.model_dump(mode="json", exclude_defaults=True)
        if file_id:
            # the location is within the parsed file, `file` of a diagnostic is the included file
            if "file" in data:
                included = Path(data.pop("file"))
                data["included"] = _relative(included, project.root) if included.is_absolute() else included.as_posix()
            if "item" in data:
                data["item"] = f"{file_id}:{data['item']}"
            data = {"file": file_id, **data}
        found.append(data)
    result, omitted = _limit(found, limit)
    answer = _list_answer("diagnostics", result, len(found), omitted)
    answer["counts"] = {name: sum(entry["severity"] == name for entry in found) for name in SEVERITIES}
    return answer


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
