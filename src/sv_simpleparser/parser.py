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

* [sv_simpleparser.parser.parse_file][]
* [sv_simpleparser.parser.parse_text][]
"""

from pathlib import Path

from . import datamodel as dm
from ._sv.parser import parse as parse_sv
from ._vhdl.parser import parse as parse_vhdl


# FIXME: Think how we want to differentiate between VHDL and SV
def parse_file(file_path: Path | str) -> dm.File:
    """Parse a SystemVerilog file.

    Args:
        file_path: Path to the SystemVerilog file.

    Returns:
        Parsed Data
    """
    if isinstance(file_path, str):
        file_path = Path(file_path)

    return parse_text(file_path.read_text(), file_path=file_path)


def parse_text(text: str, file_path: Path | str | None = None) -> dm.File:
    """Parse a SystemVerilog text.

    Args:
        text: SystemVerilog Statements.

    Keyword Args:
        file_path: Related File Path.

    Returns:
        Parsed Data
    """
    if isinstance(file_path, str):
        file_path = Path(file_path)

    if file_path and file_path.suffix in [".vhd", ".vhdl"]:
        modules = parse_vhdl(text)
    else:
        modules = parse_sv(text)

    if not modules:
        raise RuntimeError("No module found.")

    return dm.File(path=file_path, modules=modules)
