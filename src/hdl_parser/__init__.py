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

"""Easy-To-Use SystemVerilog Parser.

Usage is simple. Parse your input with one of these methods:

* [hdl_parser.parse_file][]
* [hdl_parser.parse_text][]

Macros in module headers are expanded. Macros from other files are read by

* [hdl_parser.parse_defines][]

You receive a [hdl_parser.File][] object holding all information.
"""

from .datamodel import File, MacroCall, Module, ModuleInstance, Param, Port
from .filelistparser import parse_filelist
from .parser import Macro, parse_defines, parse_defines_text, parse_file, parse_text

__all__ = [
    "File",
    "Macro",
    "MacroCall",
    "Module",
    "ModuleInstance",
    "Param",
    "Port",
    "parse_defines",
    "parse_defines_text",
    "parse_file",
    "parse_filelist",
    "parse_text",
]
