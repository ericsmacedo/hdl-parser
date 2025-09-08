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


import logging

from .. import _datamodel as _dm  # noqa: TID252
from .. import datamodel as dm  # noqa: TID252
from .lexer import SystemVerilogLexer
from .token import Module

LOGGER = logging.getLogger(__name__)


def _proc_con_tokens(con, tokens, string):
    if tokens == ("Port",):
        con.port = string
    elif tokens == ("Connection",):
        con.con = string
    elif tokens == ("PortConnection",):
        con.port = string
        con.con = string
    elif tokens == ("Comment",):
        if con.comment is None:
            con.comment = [string]
        else:
            con.comment.append(string)


def _proc_inst_tokens(mod, tokens, string, ifdefs):
    if tokens == Module.Body.Instance.Name:
        mod.name = string
    elif tokens == Module.Body.Instance.Con.Start:
        if mod.connections is None:
            mod.connections = [_dm.ConDecl(ifdefs=ifdefs)]
        else:
            mod.connections.append(_dm.ConDecl(ifdefs=ifdefs))
    elif tokens == Module.Body.Instance.Con.OrderedConnection:
        if mod.connections is None:
            mod.connections = [_dm.ConDecl(con=string, ifdefs=ifdefs)]
        else:
            mod.connections.append(_dm.ConDecl(con=string, ifdefs=ifdefs))
    elif tokens[:4] == Module.Body.Instance.Con:
        if mod.connections is not None:  # Con.Comment can trigger this
            _proc_con_tokens(mod.connections[-1], tokens[4:], string)


def _proc_port_tokens(port, tokens, string, ifdefs):  # noqa: C901
    """Processes Module.Port tokens and extract data."""
    if tokens == Module.Port.PortDirection:
        port.direction = string
    elif tokens == Module.Port.Ptype:
        port.ptype = string
    elif tokens == Module.Port.Dtype:
        port.dtype = string
    elif tokens == Module.Port.PortName:
        if port.name is None:
            port.name = [string]
            port.ifdefs = ifdefs
        else:
            port.name.append(string)
    elif tokens == Module.Port.PortWidth:
        # The dimension is packed if name is none, and unpacked if it is not None
        if port.name is None:
            port.dim = string
        elif port.dim_unpacked is None:
            port.dim_unpacked = string
    elif tokens == Module.Port.Comment:
        if port.comment is None:
            port.comment = [string]
        else:
            port.comment.append(string)


def _proc_param_tokens(self, tokens, string, ifdefs):  # noqa: C901, PLR0912
    """Processes Module.Param tokens and extract data."""
    if tokens == Module.Param.ParamType:
        self.ptype = string
    elif tokens == Module.Param.ParamName:
        if self.name is None:
            self.name = [string]
            self.ifdefs = ifdefs
        else:
            self.name.append(string)
        if self.default is None:
            self.default = [""]
        else:
            self.default.append("")
    elif tokens == Module.Param.ParamWidth:
        if self.name is None:
            self.dim = string
            self.ifdefs = ifdefs
        elif self.dim_unpacked is None:
            self.dim_unpacked = string
    elif tokens == Module.Param.Comment:
        if self.comment is None:
            self.comment = [string]
        else:
            self.comment.append(string)
    elif tokens == Module.Param.Value:
        self.default[-1] += string


def _proc_ifdef_tokens(tokens, string, ifdefs_stack, ifdefs_pop_stack):
    # Process the ifdef stack list
    if tokens[-1] == "IFDEF":
        ifdefs_stack.append(string)
    elif tokens[-1] == "IFNDEF":
        ifdefs_stack.append(_flip_ifdef(string))
    elif tokens[-1] == "ELSIF":
        ifdefs_stack[-1] = _flip_ifdef(ifdefs_stack[-1])
        ifdefs_stack.append(string)
    elif tokens[-1] == "ELSE":
        ifdefs_stack[-1] = _flip_ifdef(ifdefs_stack[-1])
    elif tokens[-1] == "ENDIF":
        del ifdefs_stack[-ifdefs_pop_stack[-1] :]

    # Process the pop stack list
    if tokens[-1] in ["IFDEF", "IFNDEF"]:
        ifdefs_pop_stack.append(1)
    elif tokens[-1] in ["ELSIF"]:
        ifdefs_pop_stack[-1] += 1
    elif tokens[-1] in ["ENDIF"]:
        del ifdefs_pop_stack[-1]

    LOGGER.debug(f"IFDEF stack: {ifdefs_stack}")
    LOGGER.debug(f"IFDEF pop stack: {ifdefs_pop_stack}")

    return ifdefs_stack, ifdefs_pop_stack


def _proc_module_tokens(self, tokens, string, ifdefs_stack):
    # Capture a new port declaration object if input/output keywords are found
    if tokens[:2] == ("Module", "Port"):
        if tokens[-1] == ("PortDirection"):
            self.port_decl.append(_dm.PortDecl(direction=string))
        else:
            _proc_port_tokens(self.port_decl[-1], tokens, string, ifdefs_stack)

    # Capture parameters, when Module.Param tokens are found
    elif tokens[:2] == ("Module", "Param"):
        if tokens is Module.Param:
            self.param_decl.append(_dm.ParamDecl())
        else:
            _proc_param_tokens(self.param_decl[-1], tokens, string, ifdefs_stack)
    # Capture Modules
    elif tokens[:2] == ("Module", "ModuleName"):
        self.name = string

    # Capture instances
    elif tokens[:3] == ("Module", "Body", "Instance"):
        if tokens == Module.Body.Instance.Module:
            self.inst_decl.append(_dm.InstDecl(module=string, ifdefs=ifdefs_stack))
        else:
            _proc_inst_tokens(self.inst_decl[-1], tokens, string, ifdefs_stack)


def _normalize_comments(comment: list[str]) -> tuple[str, ...]:
    return tuple(line.replace("\n", " ").strip() for line in comment or ())


def _normalize_defaults(default: str) -> str:
    return default.rstrip("\n").strip()


def _flip_ifdef(param):
    if param.startswith("!"):
        return param[1:]  # Removes '!' prefix
    return f"!{param}"  # Adds '!' prefix


def _normalize_ports(mod):
    for decl in mod.port_decl:
        for name in decl.name:
            yield dm.Port(
                name=name,
                direction=decl.direction,
                ptype=decl.ptype or "",
                dtype=decl.dtype or "",
                dim=decl.dim or "",
                dim_unpacked=decl.dim_unpacked or "",
                comment=_normalize_comments(decl.comment),
                ifdefs=tuple(decl.ifdefs),
            )


def _normalize_params(mod):
    for decl in mod.param_decl:
        for name, default in zip(decl.name, decl.default, strict=False):
            yield dm.Param(
                name=name,
                ptype=decl.ptype or "",
                dim=decl.dim or "",
                dim_unpacked=decl.dim_unpacked or "",
                comment=_normalize_comments(decl.comment),
                default=_normalize_defaults(default),
                ifdefs=tuple(decl.ifdefs),
            )


def _normalize_insts(mod):
    for decl in mod.inst_decl:
        yield dm.ModuleInstance(
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
                for con in (decl.connections or [])
            ),
        )


def parse(text: str) -> tuple[dm.Module, ...]:
    lexer = SystemVerilogLexer()
    module_lst = []
    ifdefs_stack: list[str] = []
    ifdefs_pop_stack: list[str] = []

    for tokens, string in lexer.get_tokens(text):
        # New module was found
        if tokens == Module.ModuleStart:
            module_lst.append(_dm.Module(ifdefs=ifdefs_stack.copy()))
        elif "IFDEF" in tokens[:]:
            _proc_ifdef_tokens(tokens, string, ifdefs_stack, ifdefs_pop_stack)
        elif "Module" in tokens[:]:
            _proc_module_tokens(module_lst[-1], tokens, string, ifdefs_stack=ifdefs_stack.copy())

    return tuple(
        dm.Module(
            name=mod.name,
            params=tuple(_normalize_params(mod)),
            ports=tuple(_normalize_ports(mod)),
            insts=tuple(_normalize_insts(mod)),
            ifdefs=tuple(mod.ifdefs),
        )
        for mod in module_lst
    )
