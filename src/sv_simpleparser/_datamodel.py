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

from dataclasses import dataclass


@dataclass
class ConDeclaration:
    """Connection.

    Attributes:
        port: Port
        con: Connection
        comment: Comment
    """

    port: str = ""
    con: str = ""
    comment: list[str] | None = None
    ifdefs: list[str] | None = None


@dataclass
class ModInstance:
    """Represents an instance of a module within another module.

    Attributes:
        name: Instance name
        module: Name of the module being instantiated
        connections: List of port connections in order of declaration
    """

    name: str | None = None
    module: str | None = None
    connections: list[ConDeclaration] | None = None
    ifdefs: list[str] | None = None


@dataclass
class PortDeclaration:
    """Represents a port declaration block in SystemVerilog.

    Attributes:
        direction: Port direction ('input', 'output', 'inout')
        ptype: Port type ('wire', 'reg', 'logic', etc.)
        name: List of port names in this declaration
        dim: Bus dim specification if applicable
        comment: List of associated comments
    """

    direction: str
    ptype: str | None = None
    dtype: str | None = None
    name: list[str] | None = None
    dim: str | None = None
    dim_unpacked: str | None = None
    comment: list[str] | None = None
    ifdefs: list[str] | None = None


@dataclass
class ParamDeclaration:
    """Represents a parameter declaration block in SystemVerilog.

    Attributes:
        ptype: Parameter type ('integer', 'real', etc.)
        name: List of parameter names in this declaration
        dim: Bus dim specification if applicable
        comment: List of associated comments
    """

    ptype: str | None = None
    name: list[str] | None = None
    dim: str | None = None
    dim_unpacked: str | None = None
    comment: list[str] | None = None
    ifdefs: list[str] | None = None
    default: str = ""


class Module:
    """Represents a complete SystemVerilog module with all its components.

    Attributes:
        name: Name of the module
        port_decl: List of PortDeclaration objects
        param_decl: List of ParamDeclaration objects
        inst_decl: List of instance declarations
    """

    def __init__(self) -> None:
        self.name: str = ""
        self.port_decl: list[PortDeclaration] = []
        self.param_decl: list[ParamDeclaration] = []
        self.inst_decl: list[ModInstance] = []
        self.ifdefs_stack: list = []
        self.ifdefs_pop_stack: list = []
