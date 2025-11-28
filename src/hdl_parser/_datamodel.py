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

import pydantic as pyd


class _BaseModel(pyd.BaseModel):
    model_config = pyd.ConfigDict(extra="forbid")


class ConDecl(_BaseModel):
    port: str = ""
    con: str = ""
    comment: list[str] | None = None
    ifdefs: list[str] | None = None


class InstDecl(_BaseModel):
    name: str | None = None
    module: str | None = None
    connections: list[ConDecl] | None = None
    ifdefs: list[str] | None = None


class PortDecl(_BaseModel):
    direction: str | None = None
    ptype: str | None = None
    dtype: str | None = None
    name: list[str] | None = None
    dim: str | None = None
    dim_unpacked: str | None = None
    comment: list[str] | None = None
    ifdefs: list[str] | None = None
    default: str = ""


class ParamDecl(_BaseModel):
    is_local: bool = False
    ptype: str | None = None
    dtype: str | None = None
    name: list[str] | None = None
    dim: str | None = None
    dim_unpacked: str | None = None
    comment: list[str] | None = None
    ifdefs: list[str] | None = None
    default: list[str] | None = None


class Module(_BaseModel):
    name: str = ""
    port_decl: list[PortDecl] = []
    param_decl: list[ParamDecl] = []
    localparam_decl: list[ParamDecl] = []
    inst_decl: list[InstDecl] = []
    ifdefs: list[str] = []
