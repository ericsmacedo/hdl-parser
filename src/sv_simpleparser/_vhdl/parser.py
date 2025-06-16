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
import re

from .. import _datamodel as _dm  # noqa: TID252
from .. import datamodel as dm  # noqa: TID252
from .lexer import VhdlLexer
from .token import Entity, Gen, Port

LOGGER = logging.getLogger(__name__)

# TODO: Decide what to do with linkage and buffer
direction_dict = {
    "in": "input",
    "out": "output",
    "inout": "inout",
    "buffer": "buffer",
}


def _proc_port_tokens(port, tokens, string):
    """Processes Module.Port tokens and extract data."""
    if tokens == Port.Direction:
        port.direction = string
    elif tokens == Port.Name:
        port.name.append(string)
    elif tokens == Port.PType:
        port.ptype = string
    elif tokens == Port.DType:
        port.dtype = string
    elif tokens == Port.Width:
        if port.dim is None:
            port.dim = string
        else:
            port.dim += string
    elif tokens == Port.Comment:
        if port.comment is None:
            port.comment = [string]
        else:
            port.comment.append(string)


def _proc_param_tokens(param, tokens, string):
    """Processes Module.Param tokens and extract data."""
    if tokens == Gen.Name:
        param.name.append(string)
    if tokens == Gen.PType:
        param.ptype = string
    elif tokens == Gen.Value:
        param.default += string
    elif tokens == Gen.Comment:
        if param.comment is None:
            param.comment = [string]
        else:
            param.comment.append(string)


def _proc_module_tokens(self, tokens, string):
    # Capture a new port declaration object if input/output keywords are found
    if tokens[:2] == Port:
        if tokens[-1] == ("NewPortDecl"):
            self.port_decl.append(_dm.PortDecl(name=[string], ifdefs=[]))
        elif self.port_decl:
            _proc_port_tokens(self.port_decl[-1], tokens, string)
    elif tokens[:2] == Gen:
        if tokens[-1] == ("NewGenDecl"):
            self.param_decl.append(_dm.ParamDecl(name=[string], ifdefs=[]))
        elif self.param_decl:
            _proc_param_tokens(self.param_decl[-1], tokens, string)


def _normalize_comments(comment: list[str]) -> tuple[str, ...]:
    return tuple(line.replace("\n", " ").strip() for line in comment or ())


def _normalize_defaults(default: str) -> str:
    return default.rstrip("\n").strip()


def _normalize_dim(dim: str) -> str:
    return f"[{re.sub(r'\s*(downto|to)\s*', ':', dim)}]" if dim else ""


def _normalize_types(ptype: str) -> str:
    return ptype.lower() if ptype else ""


def _normalize_ports(mod):
    for decl in mod.port_decl:
        for name in decl.name:
            yield dm.Port(
                name=name,
                direction=direction_dict[decl.direction],
                ptype=_normalize_types(decl.ptype),
                dtype=decl.dtype or "",
                dim=_normalize_dim(decl.dim) or "",
                dim_unpacked=decl.dim_unpacked or "",
                comment=_normalize_comments(decl.comment),
                ifdefs=tuple(decl.ifdefs),
            )


def _normalize_params(mod):
    for decl in mod.param_decl:
        for name in decl.name:
            yield dm.Param(
                name=name,
                ptype=_normalize_types(decl.ptype),
                dim=decl.dim or "",
                dim_unpacked=decl.dim_unpacked or "",
                comment=_normalize_comments(decl.comment),
                default=_normalize_defaults(decl.default),
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
                for con in decl.connections
            ),
        )


def parse(text: str) -> tuple[dm.Module, ...]:
    lexer = VhdlLexer()
    module_lst = []
    for tokens, string in lexer.get_tokens(text):
        # New entity was found
        if tokens == Entity.Name:
            module_lst.append(_dm.Module(name=string))
        elif "Entity" in tokens[:]:
            _proc_module_tokens(module_lst[-1], tokens, string)

    return tuple(
        dm.Module(
            name=mod.name,
            params=tuple(_normalize_params(mod)),
            ports=tuple(_normalize_ports(mod)),
            insts=tuple(_normalize_insts(mod)),
        )
        for mod in module_lst
    )
