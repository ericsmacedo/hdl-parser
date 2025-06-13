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

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from . import datamodel as dm
from ._hdl import SystemVerilogLexer
from ._token import Module

LOGGER = logging.getLogger(__name__)
RE_CON = re.compile(r"\s*\.(?P<port>.*)\s*\((?P<con>.*)\)\s*(//(?P<comment>.*))?")


@dataclass
class _ConDeclaration:
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

    def proc_tokens(self, token, string):
        if token == ("Port",):
            self.port = string
        elif token == ("Connection",):
            self.con = string
        elif token == ("PortConnection",):
            self.port = string
            self.con = string
        elif token == ("Comment",):
            if self.comment is None:
                self.comment = [string]
            else:
                self.comment.append(string)


@dataclass
class _ModInstance:
    """Represents an instance of a module within another module.

    Attributes:
        name: Instance name
        module: Name of the module being instantiated
        connections: List of port connections in order of declaration
    """

    name: str | None = None
    module: str | None = None
    connections: list[_ConDeclaration] | None = None
    ifdefs: list[str] | None = None

    def proc_tokens(self, token, string, ifdefs):
        if token == Module.Body.Instance.Name:
            self.name = string
        elif token == Module.Body.Instance.Con.Start:
            if self.connections is None:
                self.connections = [_ConDeclaration(ifdefs=ifdefs)]
            else:
                self.connections.append(_ConDeclaration(ifdefs=ifdefs))
        elif token == Module.Body.Instance.Con.OrderedConnection:
            if self.connections is None:
                self.connections = [_ConDeclaration(con=string, ifdefs=ifdefs)]
            else:
                self.connections.append(_ConDeclaration(con=string, ifdefs=ifdefs))
        elif token[:4] == Module.Body.Instance.Con:
            if self.connections is not None:  # Con.Comment can trigger this
                self.connections[-1].proc_tokens(token[4:], string)


@dataclass
class _PortDeclaration:
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

    def proc_tokens(self, token, string, ifdefs):  # noqa: C901
        """Processes Module.Port tokens and extract data."""
        if token == Module.Port.PortDirection:
            self.direction = string
        elif token == Module.Port.Ptype:
            self.ptype = string
        elif token == Module.Port.Dtype:
            self.dtype = string
        elif token == Module.Port.PortName:
            if self.name is None:
                self.name = [string]
                self.ifdefs = ifdefs
            else:
                self.name.append(string)
        elif token == Module.Port.PortWidth:
            # The dimension is packed if name is none, and unpacked if it is not None
            if self.name is None:
                self.dim = string
            elif self.dim_unpacked is None:
                self.dim_unpacked = string
        elif token == Module.Port.Comment:
            if self.comment is None:
                self.comment = [string]
            else:
                self.comment.append(string)


@dataclass
class _ParamDeclaration:
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

    def proc_tokens(self, token, string, ifdefs):
        """Processes Module.Param tokens and extract data."""
        if token == Module.Param.ParamType:
            self.ptype = string
        elif token == Module.Param.ParamName:
            if self.name is None:
                self.name = [string]
                self.ifdefs = ifdefs
            else:
                self.name.append(string)
        elif token == Module.Param.ParamWidth:
            if self.name is None:
                self.dim = string
                self.ifdefs = ifdefs
            elif self.dim_unpacked is None:
                self.dim_unpacked = string
        elif token == Module.Param.Comment:
            if self.comment is None:
                self.comment = [string]
            else:
                self.comment.append(string)
        elif token == Module.Param.Value:
            self.default += string


def _normalize_comments(comment: list[str]) -> tuple[str, ...]:
    return tuple(line.replace("\n", " ").strip() for line in comment or ())


def _normalize_defaults(default: str) -> str:
    return default.rstrip("\n").strip()


def _flip_ifdef(param):
    if param.startswith("!"):
        return param[1:]  # Removes '!' prefix
    return f"!{param}"  # Adds '!' prefix


class _SvModule:
    """Represents a complete SystemVerilog module with all its components.

    Attributes:
        name: Name of the module
        port_lst: List of Port objects
        param_lst: List of Param objects
        inst_list: List of ModuleInstance objects
        port_decl: List of PortDeclaration objects
        param_decl: List of ParamDeclaration objects
        inst_decl: List of instance declarations
    """

    def __init__(self):
        self.name: str | None = None
        self.port_lst: list[dm.Port] = []
        self.param_lst: list[dm.Param] = []
        self.inst_lst: list[dm.ModuleInstance] = []
        self.inst_dict: dict[str, str] = {}

        self.port_decl: list[_PortDeclaration] = []
        self.param_decl: list[_ParamDeclaration] = []
        self.inst_decl: list[_ModInstance] = []
        self.ifdefs_stack: list = []
        self.ifdefs_pop_stack: list = []

    def _gen_port_lst(self):
        for decl in self.port_decl:
            for name in decl.name:
                port = dm.Port(
                    name=name,
                    direction=decl.direction,
                    ptype=decl.ptype or "",
                    dtype=decl.dtype or "",
                    dim=decl.dim or "",
                    dim_unpacked=decl.dim_unpacked or "",
                    comment=_normalize_comments(decl.comment),
                    ifdefs=tuple(decl.ifdefs),
                )
                self.port_lst.append(port)

    def _gen_param_lst(self):
        for decl in self.param_decl:
            for name in decl.name:
                param = dm.Param(
                    name=name,
                    ptype=decl.ptype or "",
                    dim=decl.dim or "",
                    dim_unpacked=decl.dim_unpacked or "",
                    comment=_normalize_comments(decl.comment),
                    default=_normalize_defaults(decl.default),
                    ifdefs=tuple(decl.ifdefs),
                )
                self.param_lst.append(param)

    def _gen_inst_lst(self):
        for decl in self.inst_decl:
            inst = dm.ModuleInstance(
                name=decl.name,
                module=decl.module,
                ifdefs=decl.ifdefs,
                connections=tuple(
                    dm.Connection(
                        port=con.port or "",
                        con=con.con or "",
                        comment=_normalize_comments(con.comment),
                        ifdefs=tuple(con.ifdefs),
                    )
                    for con in decl.connections
                ),
            )
            self.inst_lst.append(inst)

    def proc_ifdef(self, token, string):
        # Process the ifdef stack list
        if token[-1] == "IFDEF":
            self.ifdefs_stack.append(string)
        elif token[-1] == "IFNDEF":
            self.ifdefs_stack.append(_flip_ifdef(string))
        elif token[-1] == "ELSIF":
            self.ifdefs_stack[-1] = _flip_ifdef(self.ifdefs_stack[-1])
            self.ifdefs_stack.append(string)
        elif token[-1] == "ELSE":
            self.ifdefs_stack[-1] = _flip_ifdef(self.ifdefs_stack[-1])
        elif token[-1] == "ENDIF":
            del self.ifdefs_stack[-self.ifdefs_pop_stack[-1] :]

        # Process the pop stack list
        if token[-1] in ["IFDEF", "IFNDEF"]:
            self.ifdefs_pop_stack.append(1)
        elif token[-1] in ["ELSIF"]:
            self.ifdefs_pop_stack[-1] += 1
        elif token[-1] in ["ENDIF"]:
            del self.ifdefs_pop_stack[-1]

        LOGGER.debug(f"IFDEF stack: {self.ifdefs_stack}")
        LOGGER.debug(f"IFDEF stack: {self.ifdefs_pop_stack}")

    def proc_tokens(self, token, string):
        # Capture a new port declaration object if input/output keywords are found
        if token[:2] == ("Module", "Port"):
            if token[-1] == ("PortDirection"):
                self.port_decl.append(_PortDeclaration(direction=string))
            else:
                self.port_decl[-1].proc_tokens(token, string, self.ifdefs_stack.copy())

        # Capture parameters, when Module.Param tokens are found
        elif token[:2] == ("Module", "Param"):
            if token is Module.Param:
                self.param_decl.append(_ParamDeclaration())
            else:
                self.param_decl[-1].proc_tokens(token, string, self.ifdefs_stack.copy())

        # Capture Modules
        elif token[:2] == ("Module", "ModuleName"):
            self.name = string

        # Capture instances
        elif token[:3] == ("Module", "Body", "Instance"):
            if token == Module.Body.Instance.Module:
                self.inst_decl.append(_ModInstance(module=string, ifdefs=self.ifdefs_stack.copy()))
            else:
                self.inst_decl[-1].proc_tokens(token, string, self.ifdefs_stack.copy())

        elif token[:2] == ("Module", "IFDEF"):
            self.proc_ifdef(token, string)


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

    module_lst = _parse_text(text)

    modules = tuple(
        dm.Module(
            name=mod.name,
            params=mod.param_lst,
            ports=mod.port_lst,
            insts=mod.inst_lst,
        )
        for mod in module_lst
    )

    if not modules:
        raise RuntimeError("No module found.")

    return dm.File(path=file_path, modules=modules)


def _parse_text(text: str):
    lexer = SystemVerilogLexer()
    module_lst = []
    for token, string in lexer.get_tokens(text):
        # New module was found
        if token == Module.ModuleStart:
            module_lst.append(_SvModule())
        elif "Module" in token[:]:
            module_lst[-1].proc_tokens(token, string)

    for mod in module_lst:
        mod._gen_port_lst()
        mod._gen_param_lst()
        mod._gen_inst_lst()

    return module_lst
