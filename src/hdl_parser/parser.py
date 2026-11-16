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


"""The parser.

The parser offers two methods:

* [hdl_parser.parser.parse_file][]
* [hdl_parser.parser.parse_text][]

Macros are expanded on request (`expand_macros`), if they are defined in the same file, in an included file
or handed over via `macros`.
Use [hdl_parser.parser.parse_defines][] to read macros from other files:

* [hdl_parser.parser.parse_defines][]
* [hdl_parser.parser.parse_defines_text][]
"""

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, NamedTuple, TypeAlias

from . import datamodel as dm
from ._diagnostics import Diagnostics
from ._ids import assign_ids
from ._sv.parser import parse as parse_sv
from ._sv.preproc import Macro, Macros, collect_defines, read_text
from ._vhdl.parser import parse as parse_vhdl

LOGGER = logging.getLogger(__name__)

Lang: TypeAlias = Literal["sv", "vhdl"]
"""Language."""

LANGMAP: dict[str, Lang] = {
    ".sv": "sv",
    ".v": "sv",
    ".vhd": "vhdl",
    ".vhdl": "vhdl",
}


def parse_defines(
    *file_paths: Path | str, inc_dirs: Iterable[Path | str] = (), resolve_ifdefs: bool = False
) -> dict[str, Macro]:
    """Read `` `define `` macros from SystemVerilog files.

    Args:
        file_paths: Paths to the files, typically header files (`*.svh`).

    Keyword Args:
        inc_dirs: Include directories. Included files are searched next to the including file and here.
        resolve_ifdefs: Resolve `` `ifdef `` conditions on macros which are known to be defined.

    Returns:
        Macros, to be handed over to [hdl_parser.parser.parse_file][] or [hdl_parser.parser.parse_text][].

    The files are read in the given order, from top to bottom: a later `` `define `` replaces an earlier one,
    `` `undef `` and `` `include `` statements are followed.
    Macros with different definitions under unknown `` `ifdef `` conditions are skipped.
    """
    return collect_defines(
        file_paths=map(Path, file_paths), inc_dirs=map(Path, inc_dirs), resolve_ifdefs=resolve_ifdefs
    )


def parse_defines_text(
    *texts: str, inc_dirs: Iterable[Path | str] = (), resolve_ifdefs: bool = False
) -> dict[str, Macro]:
    """Read `` `define `` macros from SystemVerilog text.

    Args:
        texts: SystemVerilog Statements.

    Keyword Args:
        inc_dirs: Include directories. Included files are searched here.
        resolve_ifdefs: Resolve `` `ifdef `` conditions on macros which are known to be defined.

    Returns:
        Macros, to be handed over to [hdl_parser.parser.parse_file][] or [hdl_parser.parser.parse_text][].

    See [hdl_parser.parser.parse_defines][] for limitations.
    """
    return collect_defines(texts=texts, inc_dirs=map(Path, inc_dirs), resolve_ifdefs=resolve_ifdefs)


def parse_file(  # noqa: PLR0913
    file_path: Path | str,
    lang: Lang | None = None,
    encoding: str | None = None,
    expand_macros: bool = False,
    macros: Macros | None = None,
    inc_dirs: Iterable[Path | str] = (),
    resolve_ifdefs: bool = False,
    closed_world: bool = False,
    maybe_defined: Iterable[str] = (),
) -> dm.File:
    """Parse a HDL (SystemVerilog or VHDL) file.

    Args:
        file_path: Path to the file.

    Keyword Args:
        lang: Language: SystemVerilog (sv) or (VHDL). Detected from file_path. `sv` by default.
        encoding: File encoding. By default the file is read as UTF-8, with a fallback to
                  Latin-1 if it is not valid UTF-8 (common for legacy HDL sources with
                  non-ASCII characters in comments). If given, the encoding is used strictly
                  and a `UnicodeDecodeError` is raised on invalid input.
        expand_macros: Expand macros with known definition. Macros defined in the file and in the files it
                       includes are known. SystemVerilog only.
        macros: Macros defined outside of this file and its included files.
                See [hdl_parser.parser.parse_defines][]. Requires `expand_macros`.
        inc_dirs: Include directories. Included files are searched next to the file and here.
                  Used by `expand_macros` only. Included files are always read as UTF-8 with a fallback
                  to Latin-1.
        resolve_ifdefs: Resolve `` `ifdef `` conditions on macros which are known to be defined: code which is
                        not compiled is removed, the remaining code is no longer tagged with this condition.
                        Conditions on any other macro are kept. Requires `expand_macros`.
        closed_world: All definitions are known: a macro which is neither defined by `macros`, the file and its
                      included files, nor named by `maybe_defined` is undefined, like for a compiler. Conditions on
                      it are resolved too. Ends at an included file which is not found. Requires `resolve_ifdefs`.
        maybe_defined: Names of macros which other files may define. Conditions on them stay unknown.

    Returns:
        Parsed Data
    """
    if isinstance(file_path, str):
        file_path = Path(file_path)

    return parse_text(
        read_text(file_path, encoding),
        file_path=file_path,
        lang=lang,
        expand_macros=expand_macros,
        macros=macros,
        inc_dirs=inc_dirs,
        resolve_ifdefs=resolve_ifdefs,
        closed_world=closed_world,
        maybe_defined=maybe_defined,
    )


def parse_text(  # noqa: PLR0913
    text: str,
    file_path: Path | str | None = None,
    lang: Lang | None = None,
    expand_macros: bool = False,
    macros: Macros | None = None,
    inc_dirs: Iterable[Path | str] = (),
    resolve_ifdefs: bool = False,
    closed_world: bool = False,
    maybe_defined: Iterable[str] = (),
) -> dm.File:
    """Parse HDL (SystemVerilog or VHDL) text.

    Args:
        text: HDL Statements.

    Keyword Args:
        file_path: Related File Path.
        lang: Language: SystemVerilog (sv) or (VHDL). Detected from file_path. `sv` by default.
        expand_macros: Expand macros with known definition. Macros defined in the text and in the files it
                       includes are known. SystemVerilog only.
        macros: Macros defined outside of this text and its included files.
                See [hdl_parser.parser.parse_defines][]. Requires `expand_macros`.
        inc_dirs: Include directories. Included files are searched next to `file_path` and here.
                  Used by `expand_macros` only.
        resolve_ifdefs: Resolve `` `ifdef `` conditions on macros which are known to be defined: code which is
                        not compiled is removed, the remaining code is no longer tagged with this condition.
                        Conditions on any other macro are kept. Requires `expand_macros`.
        closed_world: All definitions are known: a macro which is neither defined by `macros`, the file and its
                      included files, nor named by `maybe_defined` is undefined, like for a compiler. Conditions on
                      it are resolved too. Ends at an included file which is not found. Requires `resolve_ifdefs`.
        maybe_defined: Names of macros which other files may define. Conditions on them stay unknown.

    Returns:
        Parsed Data. `modules` is empty, if there is no module (i.e. a file with packages only).
        SystemVerilog packages are listed in `packages`, interfaces in `interfaces`.
    """
    if macros and not expand_macros:
        raise ValueError("'macros' requires 'expand_macros=True'.")
    if resolve_ifdefs and not expand_macros:
        raise ValueError("'resolve_ifdefs' requires 'expand_macros=True'.")
    if closed_world and not resolve_ifdefs:
        raise ValueError("'closed_world' requires 'resolve_ifdefs=True'.")

    if isinstance(file_path, str):
        file_path = Path(file_path)

    if lang is None and file_path:
        lang = LANGMAP.get(file_path.suffix)

    diagnostics = Diagnostics(str(file_path) if file_path else "<text>")
    if lang == "vhdl":
        file = assign_ids(parse_vhdl(text, diagnostics), casefold=True)
    else:
        file = parse_sv(
            text,
            file_path=file_path,
            expand_macros=expand_macros,
            macros=macros,
            inc_dirs=map(Path, inc_dirs),
            resolve_ifdefs=resolve_ifdefs,
            diagnostics=diagnostics,
            closed_world=closed_world,
            maybe_defined=maybe_defined,
        )
        file = assign_ids(file)

    units: tuple[dm.Module | dm.Package, ...] = (*file.modules, *file.interfaces, *file.packages)
    if not units:
        # this is fine: included files, classes, ...
        diagnostics.add("no-module", "no module found.")
    for module in (*file.modules, *file.interfaces):
        for macro in module.unresolved_macros:
            diagnostics.add(
                "macro-not-expanded",
                f"module '{module.name}': macro `{macro.name} in module header is not expanded. "
                "Ports or parameters may be missing.",
                macro.loc,
                item=macro.id,
            )
        _check_drivers(module, diagnostics, casefold=lang == "vhdl")

    update = {"path": file_path, "lang": "vhdl" if lang == "vhdl" else "sv", "diagnostics": diagnostics.finish(units)}
    return file.model_copy(update=update)


_RESOLVED = frozenset(("tri", "tri0", "tri1", "triand", "trior", "trireg", "wand", "wor", "supply0", "supply1"))
"""Net types resolving multiple drivers."""


class _Driver(NamedTuple):
    """One Statement Driving A Signal: A Continuous Assignment Or A Process."""

    select: str
    generates: tuple[dm.Generate, ...]
    ifdefs: frozenset[str]
    loc: dm.Location | None
    process: int | None
    """Index of the process. `None` for a continuous assignment."""


def _conflict(one: _Driver, other: _Driver) -> bool:
    """`one` and `other` may drive the same bits at the same time."""
    if one.process is not None and one.process == other.process:
        return False
    if one.select and other.select and one.select != other.select:
        # different bits, or not known
        return False
    # alternatives of a generate `if` or `case`, or constructs which may be active alone: assumed to be fine
    depth = min(len(one.generates), len(other.generates))
    if one.generates[:depth] != other.generates[:depth]:
        return False
    # alternatives of an `ifdef`
    return not any(f"!{cond}" in other.ifdefs for cond in one.ifdefs) and not any(
        f"!{cond}" in one.ifdefs for cond in other.ifdefs
    )


def _drivers(module: dm.Module, casefold: bool) -> dict[str, list[_Driver]]:
    """Drivers of the signals and ports of `module`, by name (case folded with `casefold`).

    Bidirectional ports and nets resolving multiple drivers are left out, as well as variables of processes.
    """

    def norm(name: str) -> str:
        return name.casefold() if casefold else name

    items: tuple[dm.Port | dm.Signal, ...] = (*module.ports, *module.signals)
    declared = {
        norm(item.name)
        for item in items
        if item.ptype not in _RESOLVED and not (isinstance(item, dm.Port) and item.direction == "inout")
    }
    drivers: dict[str, list[_Driver]] = {}
    for assign in module.assigns:
        target = norm(assign.target)
        if target in declared:
            driver = _Driver(assign.select, assign.generates, frozenset(assign.ifdefs), assign.loc, None)
            drivers.setdefault(target, []).append(driver)
    for idx, process in enumerate(module.processes):
        seen: set[tuple[str, str]] = set()
        for assign in process.assigns:
            target = norm(assign.target)
            # VHDL variables are assigned blocking
            if target not in declared or (target, assign.select) in seen or (casefold and assign.blocking):
                continue
            seen.add((target, assign.select))
            ifdefs = frozenset((*process.ifdefs, *assign.ifdefs))
            drivers.setdefault(target, []).append(_Driver(assign.select, process.generates, ifdefs, assign.loc, idx))
    return drivers


def _check_drivers(module: dm.Module, diagnostics: Diagnostics, casefold: bool = False) -> None:
    """Report signals and ports of `module`, which are driven by more than one statement.

    Every continuous assignment is a driver, every process is one. Variables of a process and loop variables are
    left out, as well as drivers of different bits, different generate constructs or different `` `ifdef ``
    branches. Bidirectional ports and nets resolving multiple drivers (`tri`, `wand`, ...) are fine.
    """
    items: tuple[dm.Port | dm.Signal, ...] = (*module.ports, *module.signals)
    by_name = {(item.name.casefold() if casefold else item.name): item for item in reversed(items)}
    for target, drivers in _drivers(module, casefold).items():
        involved = [
            driver for driver in drivers if any(driver is not other and _conflict(driver, other) for other in drivers)
        ]
        if not involved:
            continue
        item = by_name[target]
        lines = ", ".join(str(driver.loc.line) for driver in involved if driver.loc)
        diagnostics.add(
            "multiple-drivers",
            f"'{item.name}' is driven by {len(involved)} statements (lines {lines}).",
            involved[1].loc,
            item=item.id,
        )
