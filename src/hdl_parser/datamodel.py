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

"""Data Model."""

from pathlib import Path

import pydantic as pyd


class _BaseModel(pyd.BaseModel):
    model_config = pyd.ConfigDict(frozen=True, extra="forbid")

    @property
    def overview(self) -> str:
        """JSON compatible Overview."""
        return self.model_dump_json(indent=2, exclude_defaults=True)


class Location(_BaseModel):
    """Source Location.

    Lines and columns start at 1. Columns count characters, not bytes. The end is exclusive: `end_col` is
    the column behind the last character.

    Code created by a macro points at the macro call in the parsed file. Nested macros point at the outermost
    call.

    Attributes:
        line: First line.
        col: First column.
        end_line: Last line.
        end_col: Column behind the last character on `end_line`.
        macro: Name of the macro (without backtick), which created the item. Empty, if the item is written in
               the source. The item cannot be edited directly, but only via the macro call.
    """

    line: int
    col: int
    end_line: int
    end_col: int
    macro: str = ""


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
        localparams: Local Parameters
        insts: Submodule Instances.
        ifdefs: Conditions the module is defined at.
        unresolved_macros: Macros used in the module header, which could not be expanded.
                           Ports or parameters defined by these macros are missing.
        loc: Source Location: from `module` to `endmodule`. VHDL: the entity.
    """

    name: str
    params: tuple["Param", ...] = ()
    ports: tuple["Port", ...] = ()
    localparams: tuple["Param", ...] = ()
    insts: tuple["ModuleInstance", ...] = ()
    ifdefs: tuple[str, ...] = ()
    unresolved_macros: tuple["MacroCall", ...] = ()
    loc: Location | None = None


class Param(_BaseModel):
    """Represents a parameter in a SystemVerilog module.

    Attributes:
        ptype: Parameter type ('integer', 'real', 'string', etc.)
        name: Name of the parameter
        dim: Dimension (Packed)
        dim_unpacked: Unpacked Dimension
        comment: tuple of associated comments
        loc: Source Location of the declaration. Names declared together share it.
    """

    ptype: str = ""
    name: str
    dim: str = ""
    dim_unpacked: str = ""
    default: str = ""
    ifdefs: tuple[str, ...] = ()
    comment: tuple[str, ...] = ()
    loc: Location | None = None


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
        loc: Source Location of the declaration. Names declared together share it.
    """

    # FIXME: Decide for possible values (remove comments)
    direction: str = ""  # Literal["input", "output", "inout", "buffer"]
    ptype: str = ""  # Literal["reg", "wire", "logic", "std_logic", "std_logic_vector", "std_ulogic", ""] = ""
    dtype: str = ""  # Literal["unsigned", "signed", ""] = ""
    name: str
    dim: str = ""
    dim_unpacked: str = ""
    ifdefs: tuple[str, ...] = ()
    comment: tuple[str, ...] = ()
    loc: Location | None = None


class Connection(_BaseModel):
    """Connection.

    Attributes:
        port: Port
        con: Connection
        comment: Comment
        loc: Source Location: `.port(con)`, `port => con` or the expression of a connection by order.
    """

    port: str = ""
    con: str = ""
    comment: tuple[str, ...] = ()
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None


class ModuleInstance(_BaseModel):
    """Represents An Instance Of A Module Within Another Module.

    Attributes:
        name: Module Instance Name
        module: Module Name
        connections: Connections
        loc: Source Location of the instantiation. Instances created together share it.
    """

    name: str
    module: str
    connections: tuple[Connection, ...] = ()
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None


class MacroCall(_BaseModel):
    """Represents The Use Of A Macro.

    Attributes:
        name: Macro Name, without backtick
        args: Arguments. `None` if the macro is used without parenthesis
        ifdefs: Conditions the macro is used at
        loc: Source Location of the call, including the arguments.
    """

    name: str
    args: tuple[str, ...] | None = None
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None
