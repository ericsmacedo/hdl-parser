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

"""Data Model."""

from pathlib import Path
from typing import Literal

import pydantic as pyd


class _BaseModel(pyd.BaseModel):
    model_config = pyd.ConfigDict(frozen=True, extra="forbid")

    @property
    def overview(self) -> str:
        """JSON compatible Overview."""
        return self.model_dump_json(indent=2, exclude_defaults=True)


class File(_BaseModel):
    """Represents a SystemVerilog File with SystemVerilog Modules.

    Attributes:
        path: Related File.
        modules: Modules Within That File.
    """

    path: Path | None
    modules: tuple["Module", ...]


class Module(_BaseModel):
    """Represents a SystemVerilog Module with parameters, ports and submodules.

    Attributes:
        name: Module Name
        params: Parameters
        ports: Ports
        insts: Submodule Instances.
    """

    name: str
    params: tuple["Param", ...] = ()
    ports: tuple["Port", ...] = ()
    insts: tuple["ModuleInstance", ...] = ()


class Param(_BaseModel):
    """Represents a parameter in a SystemVerilog module.

    Attributes:
        ptype: Parameter type ('integer', 'real', 'string', etc.)
        name: Name of the parameter
        dim: Dimension (Packed)
        dim_unpacked: Unpacked Dimension
        comment: tuple of associated comments
    """

    ptype: str = ""
    name: str
    dim: str = ""
    dim_unpacked: str = ""
    default: str = ""
    ifdefs: tuple[str, ...] = ()
    comment: tuple[str, ...] = ()


class Port(_BaseModel):
    """Represents a port in a SystemVerilog module.

    Attributes:
        direction: Port Direction
        ptype: Port Type
        dtype: Data Type
        name: Name of the port
        dim: Dimension (Packed)
        dim_unpacked: Unpacked
        comment: tuple of associated comments
    """

    direction: Literal["input", "output", "inout"]
    ptype: Literal["reg", "wire", "logic", ""] = ""
    dtype: Literal["unsigned", "signed", ""] = ""
    name: str
    dim: str = ""
    dim_unpacked: str = ""
    ifdefs: tuple[str, ...] = ()
    comment: tuple[str, ...] = ()


class Connection(_BaseModel):
    """Connection.

    Attributes:
        port: Port
        con: Connection
        comment: Comment
    """

    port: str = ""
    con: str = ""
    comment: tuple[str, ...] = ()
    ifdefs: tuple[str, ...] = ()


class ModuleInstance(_BaseModel):
    """Represents An Instance Of A Module Within Another Module.

    Attributes:
        name: Module Instance Name
        module: Module Name
        connections: Connections
    """

    name: str
    module: str
    connections: tuple[Connection, ...] = ()
    ifdefs: tuple[str, ...] = ()
