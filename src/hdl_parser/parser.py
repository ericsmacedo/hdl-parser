# MIT License
#
# Copyright (c) 2025 ericsmacedo
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
"""

from pathlib import Path
from typing import Literal, TypeAlias

from . import datamodel as dm
from ._sv.parser import parse as parse_sv

Lang: TypeAlias = Literal["sv", "vhdl"]
"""Language."""

LANGMAP: dict[str, Lang] = {
    ".sv": "sv",
    ".v": "sv",
    ".vhd": "vhdl",
    ".vhdl": "vhdl",
}


def parse_file(file_path: Path | str, lang: Lang | None = None) -> dm.File:
    """Parse a HDL (SystemVerilog or VHDL) file.

    Args:
        file_path: Path to the file.

    Keyword Args:
        lang: Language: SystemVerilog (sv) or (VHDL). Detected from file_path. `sv` by default.

    Returns:
        Parsed Data
    """
    if isinstance(file_path, str):
        file_path = Path(file_path)

    return parse_text(file_path.read_text(), file_path=file_path, lang=lang)


def parse_text(text: str, file_path: Path | str | None = None, lang: Lang | None = None) -> dm.File:
    """Parse HDL (SystemVerilog or VHDL) text.

    Args:
        text: HDL Statements.

    Keyword Args:
        file_path: Related File Path.
        lang: Language: SystemVerilog (sv) or (VHDL). Detected from file_path. `sv` by default.

    Returns:
        Parsed Data
    """
    if isinstance(file_path, str):
        file_path = Path(file_path)

    if lang is None and file_path:
        lang = LANGMAP[file_path.suffix]

    if lang == "vhdl":
        raise RuntimeError("VHDL parsing is not supported yet.")
        # modules = parse_vhdl(text)
    modules = parse_sv(text)

    if not modules:
        raise RuntimeError("No module found.")

    return dm.File(path=file_path, modules=modules)
