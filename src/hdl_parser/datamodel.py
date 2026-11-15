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

from collections.abc import Iterator
from pathlib import Path
from typing import Literal, TypeAlias, Union

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


Severity: TypeAlias = Literal["error", "warning", "info"]
"""Severity Of A Diagnostic."""


class Diagnostic(_BaseModel):
    """A Problem Found While Parsing.

    The result is still valid, but it may be incomplete at the reported location.

    | `code`                | Severity | Meaning                                                           |
    | --------------------- | -------- | ----------------------------------------------------------------- |
    | `macro-not-expanded`  | warning  | Macro in a module header is not expanded. `item` is the macro.    |
    | `macro-ambiguous`     | warning  | Macro has different definitions under unknown conditions.         |
    | `macro-recursive`     | warning  | Macro uses itself.                                                |
    | `macro-args-missing`  | warning  | Macro with arguments is used without.                             |
    | `macro-args-count`    | warning  | Macro is used with the wrong number of arguments.                 |
    | `macro-bad-define`    | warning  | `` `define `` cannot be parsed.                                   |
    | `include-not-found`   | warning  | Included file is not found.                                       |
    | `include-unreadable`  | warning  | Included file cannot be read.                                     |
    | `header-item-skipped` | warning  | Code within a parameter or port list is not understood.           |
    | `missing-end`         | warning  | Module, entity or architecture without end.                       |
    | `unbalanced-bracket`  | warning  | Bracket is never closed.                                          |
    | `no-module`           | info     | File without module, interface or package, i.e. an included file. |

    The macros of the `macro-*` codes are not expanded, the macros of a file of the `include-*` codes are
    unknown. In both cases and on `header-item-skipped`, parameters or ports may be missing.

    Code the parser has no interest in (i.e. procedural code) is skipped without diagnostic.

    Attributes:
        code: Kind of problem. See table above.
        severity: `error`, `warning` or `info`.
        message: Description.
        loc: Source Location within the parsed file. A problem within an included file points to the
             `` `include `` statement.
        item: Identifier of the related item: the module the problem is located in, if not stated otherwise.
        file: Included file the problem is located in. Empty, if located in the parsed file itself.
    """

    code: str
    severity: Severity
    message: str
    loc: Location | None = None
    item: str = ""
    file: str = ""


Item: TypeAlias = Union[
    "Module",
    "Interface",
    "Package",
    "Param",
    "Port",
    "Modport",
    "Typedef",
    "Member",
    "ModuleInstance",
    "Connection",
    "MacroCall",
]
"""Any Item With An Identifier."""


class File(_BaseModel):
    """Represents a SystemVerilog File with SystemVerilog Modules.

    Every item has an `id`, which is unique within the file and stable: it is built from names only, so it
    does not change on unrelated edits. It follows the hierarchical names of SystemVerilog:

    | Item                                     | `id`                 |
    | ---------------------------------------- | -------------------- |
    | Module, interface, package               | `top`, `bus_pkg`     |
    | Modport, port of a modport               | `bus_if.master.req`  |
    | Parameter, local parameter, port         | `top.WIDTH`          |
    | Type                                     | `bus_pkg.req_t`      |
    | Enum member, struct or union field       | `bus_pkg.req_t.addr` |
    | Instance                                 | `top.u_sub`          |
    | Instance within labeled generate blocks  | `top.g_a.u_sub`      |
    | Connection, parameter value by name      | `top.u_sub.clk`      |
    | Connection by order (first, second, ...) | `top.u_sub.#1`       |
    | Parameter value by order                 | `top.u_sub.#p1`      |
    | Unresolved macro call in the header      | ``top.`PORTS``       |

    A name used again (i.e. in two `` `ifdef `` branches) gets a suffix: `top.a`, `top.a~2`.
    VHDL names are lower case, as VHDL is case insensitive.
    The characters `.:#~%` and white space within names are percent-encoded.

    The full identifier adds the file: `rtl/top.sv:top.u_sub` (see [full_id][hdl_parser.datamodel.File.full_id]).

    Attributes:
        path: Related File.
        modules: Modules Within That File.
        interfaces: Interfaces Within That File.
        packages: Packages Within That File.
        diagnostics: Problems found while parsing, in the order of the file.
    """

    path: Path | None
    modules: tuple["Module", ...]
    interfaces: tuple["Interface", ...] = ()
    packages: tuple["Package", ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def file_id(self) -> str:
        """File part of the full identifiers.

        The path with forward slashes, relative to the current directory if it is located there.
        `<text>` without path.
        """
        path = self.path
        if path is None:
            return "<text>"
        if path.is_absolute():
            try:
                path = path.relative_to(Path.cwd())
            except ValueError:
                pass
        return path.as_posix()

    def full_id(self, item: "Item | str") -> str:
        """Full identifier of `item` (or of a local identifier): `<file>:<id>`."""
        local = item if isinstance(item, str) else item.id
        return f"{self.file_id}:{local}"

    def iter_items(self) -> Iterator["Item"]:
        """All items: packages, interfaces and modules with their parameters, types, ports, instances and so on."""
        for package in self.packages:
            yield package
            yield from package.params
            yield from package.localparams
            for typedef in package.typedefs:
                yield typedef
                yield from typedef.members
        for module in (*self.interfaces, *self.modules):
            yield module
            yield from module.params
            yield from module.localparams
            yield from module.ports
            for typedef in module.typedefs:
                yield typedef
                yield from typedef.members
            yield from module.unresolved_macros
            for modport in getattr(module, "modports", ()):
                yield modport
                yield from modport.ports
            for inst in module.insts:
                yield inst
                yield from inst.params
                yield from inst.connections

    def find(self, id_: str) -> "Item | None":
        """Item with the identifier `id_`: local (`top.a`) or full (`rtl/top.sv:top.a`). `None` if not found."""
        if ":" in id_:
            # local identifiers never contain a colon, the file part might
            file_id, id_ = id_.rsplit(":", 1)
            if file_id != self.file_id:
                return None
        return next((item for item in self.iter_items() if item.id == id_), None)


class Module(_BaseModel):
    """Represents a SystemVerilog Module with parameters, ports and submodules.

    Attributes:
        name: Module Name
        params: Parameters
        ports: Ports
        localparams: Local Parameters
        typedefs: Types declared within the module.
        insts: Submodule Instances.
        ifdefs: Conditions the module is defined at.
        unresolved_macros: Macros used in the module header, which could not be expanded.
                           Ports or parameters defined by these macros are missing.
        loc: Source Location: from `module` to `endmodule`. VHDL: the entity.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    params: tuple["Param", ...] = ()
    ports: tuple["Port", ...] = ()
    localparams: tuple["Param", ...] = ()
    typedefs: tuple["Typedef", ...] = ()
    insts: tuple["ModuleInstance", ...] = ()
    ifdefs: tuple[str, ...] = ()
    unresolved_macros: tuple["MacroCall", ...] = ()
    loc: Location | None = None


class Modport(_BaseModel):
    """Represents a modport of a SystemVerilog interface: `modport master (output req, input ack);`.

    Attributes:
        name: Name of the modport
        ports: Signals of the interface with their direction. Just `name` and `direction` are set.
               Imported and exported tasks and functions, and clocking blocks are not listed.
        comment: tuple of associated comments
        ifdefs: Conditions the modport is defined at.
        loc: Source Location. Modports declared together share it.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    ports: tuple["Port", ...] = ()
    comment: tuple[str, ...] = ()
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None


class Interface(Module):
    """Represents a SystemVerilog Interface. It has everything a module has, and modports.

    Attributes:
        modports: Modports
    """

    modports: tuple[Modport, ...] = ()


class Package(_BaseModel):
    """Represents a SystemVerilog Package with parameters and types.

    Attributes:
        name: Package Name
        params: Parameters
        localparams: Local Parameters
        typedefs: Types
        ifdefs: Conditions the package is defined at.
        loc: Source Location: from `package` to `endpackage`.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    params: tuple["Param", ...] = ()
    localparams: tuple["Param", ...] = ()
    typedefs: tuple["Typedef", ...] = ()
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None


class Member(_BaseModel):
    """Member Of An Enumeration, Or Field Of A Struct Or Union.

    Attributes:
        name: Name
        dtype: Data type of a field: `logic`, `logic signed`, `pkg::other_t`. Empty for enumeration members.
        dim: Dimension (Packed) of a field.
        dim_unpacked: Unpacked dimension of a field. Range of an enumeration member: `[3]` of `NAME[3]`.
        value: Value of an enumeration member, or default of a field. Empty, if not given.
        comment: tuple of associated comments
        ifdefs: Conditions the member is defined at.
        loc: Source Location. Fields declared together share it.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    dtype: str = ""
    dim: str = ""
    dim_unpacked: str = ""
    value: str = ""
    comment: tuple[str, ...] = ()
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None


class Typedef(_BaseModel):
    """Represents a type: `typedef ... name;`.

    | `typedef`                                      | `kind`   | `dtype`  | `dim`   | `members` |
    | ---------------------------------------------- | -------- | -------- | ------- | --------- |
    | `typedef logic [7:0] byte_t;`                  | `alias`  | `logic`  | `[7:0]` |           |
    | `typedef enum logic [1:0] {IDLE, BUSY} st_t;`  | `enum`   | `logic`  | `[1:0]` | 2         |
    | `typedef struct packed {logic a;} req_t;`      | `struct` | `packed` |         | 1         |
    | `typedef union {int i; real r;} num_t;`        | `union`  |          |         | 2         |

    Attributes:
        name: Name of the type
        kind: `alias`, `enum`, `struct` or `union`.
        dtype: Aliased type, base type of an enumeration or qualifiers of a struct or union.
        dim: Dimension (Packed)
        dim_unpacked: Unpacked Dimension
        members: Members of an enumeration, fields of a struct or union.
        comment: tuple of associated comments
        ifdefs: Conditions the type is defined at.
        loc: Source Location: from `typedef` to `;`.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    kind: Literal["alias", "enum", "struct", "union"]
    dtype: str = ""
    dim: str = ""
    dim_unpacked: str = ""
    members: tuple[Member, ...] = ()
    comment: tuple[str, ...] = ()
    ifdefs: tuple[str, ...] = ()
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
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
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
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
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
    """Connection Of A Port, Or Value Of A Parameter, Of An Instance.

    Attributes:
        port: Name of the port or parameter. Empty, if connected by order.
        con: Connected expression, or value of the parameter.
        comment: Comment
        ifdefs: Conditions the connection is made at.
        loc: Source Location: `.port(con)`, `port => con` or the expression of a connection by order.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    port: str = ""
    con: str = ""
    comment: tuple[str, ...] = ()
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None


GenerateKind: TypeAlias = Literal["if", "else", "for", "case", "begin", "block"]
"""Kind Of Generate Construct."""


class Generate(_BaseModel):
    """Generate Construct An Instance Is Located In.

    | SystemVerilog                     | VHDL                               | `kind` | `name` | `cond`      |
    | --------------------------------- | ---------------------------------- | ------ | ------ | ----------- |
    | `if (A) begin : g_a`              | `g_a : if A generate`              | `if`   | `g_a`  | `A`         |
    | `else begin : g_b`                |                                    | `else` | `g_b`  |             |
    | `for (i = 0; i < N; i++) begin`   | `g : for i in 0 to N-1 generate`   | `for`  |        | `i = 0; ...`|
    | `case (W)`                        | `g : case W generate`              | `case` |        | `W`         |
    | `begin : g_c` (i.e. a case item)  |                                    | `begin`| `g_c`  |             |
    |                                   | `b : block`                        | `block`| `b`    |             |

    An instance within a `for` is created multiple times.

    Attributes:
        kind: Kind of construct. See table above.
        name: Label. Empty for blocks without label, and constructs without `begin`.
        cond: Condition of `if`, loop of `for` or expression of `case`.
    """

    kind: GenerateKind
    name: str = ""
    cond: str = ""


class ModuleInstance(_BaseModel):
    """Represents An Instance Of A Module Within Another Module.

    Attributes:
        name: Module Instance Name
        module: Module Name
        dim: Dimension of an array of instances: `[3:0]`.
        params: Parameter values: `#(.WIDTH(8))`, or `generic map (WIDTH => 8)` in VHDL.
        connections: Connections
        generates: Generate constructs the instance is located in, from the outermost to the innermost.
        ifdefs: Conditions the instance is created at.
        loc: Source Location of the instantiation. Instances created together share it.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    module: str
    dim: str = ""
    params: tuple[Connection, ...] = ()
    connections: tuple[Connection, ...] = ()
    generates: tuple[Generate, ...] = ()
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None


class MacroCall(_BaseModel):
    """Represents The Use Of A Macro.

    Attributes:
        name: Macro Name, without backtick
        args: Arguments. `None` if the macro is used without parenthesis
        ifdefs: Conditions the macro is used at
        loc: Source Location of the call, including the arguments.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    args: tuple[str, ...] | None = None
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None
