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

from collections.abc import Iterable
from pathlib import Path
from typing import Literal, TypeAlias

from . import datamodel as dm
from ._sv.parser import parse as parse_sv
from ._sv.preproc import Macro, Macros, collect_defines
from ._vhdl.parser import parse as parse_vhdl

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
    expand_macros: bool = False,
    macros: Macros | None = None,
    inc_dirs: Iterable[Path | str] = (),
    resolve_ifdefs: bool = False,
) -> dm.File:
    """Parse a HDL (SystemVerilog or VHDL) file.

    Args:
        file_path: Path to the file.

    Keyword Args:
        lang: Language: SystemVerilog (sv) or (VHDL). Detected from file_path. `sv` by default.
        expand_macros: Expand macros with known definition. Macros defined in the file and in the files it
                       includes are known. SystemVerilog only.
        macros: Macros defined outside of this file and its included files.
                See [hdl_parser.parser.parse_defines][]. Requires `expand_macros`.
        inc_dirs: Include directories. Included files are searched next to the file and here.
                  Used by `expand_macros` only.
        resolve_ifdefs: Resolve `` `ifdef `` conditions on macros which are known to be defined: code which is
                        not compiled is removed, the remaining code is no longer tagged with this condition.
                        Conditions on any other macro are kept. Requires `expand_macros`.

    Returns:
        Parsed Data
    """
    if isinstance(file_path, str):
        file_path = Path(file_path)

    return parse_text(
        file_path.read_text(),
        file_path=file_path,
        lang=lang,
        expand_macros=expand_macros,
        macros=macros,
        inc_dirs=inc_dirs,
        resolve_ifdefs=resolve_ifdefs,
    )


def parse_text(  # noqa: PLR0913
    text: str,
    file_path: Path | str | None = None,
    lang: Lang | None = None,
    expand_macros: bool = False,
    macros: Macros | None = None,
    inc_dirs: Iterable[Path | str] = (),
    resolve_ifdefs: bool = False,
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

    Returns:
        Parsed Data
    """
    if macros and not expand_macros:
        raise ValueError("'macros' requires 'expand_macros=True'.")
    if resolve_ifdefs and not expand_macros:
        raise ValueError("'resolve_ifdefs' requires 'expand_macros=True'.")

    if isinstance(file_path, str):
        file_path = Path(file_path)

    if lang is None and file_path:
        lang = LANGMAP[file_path.suffix]

    if lang == "vhdl":
        modules = parse_vhdl(text)
    else:
        modules = parse_sv(
            text,
            file_path=file_path,
            expand_macros=expand_macros,
            macros=macros,
            inc_dirs=map(Path, inc_dirs),
            resolve_ifdefs=resolve_ifdefs,
        )

    if not modules:
        raise RuntimeError("No module found.")

    return dm.File(path=file_path, modules=modules)
