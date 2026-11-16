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
    | `file-not-found`      | error    | File does not exist.                                              |
    | `file-unreadable`     | error    | File cannot be read.                                              |
    | `parse-failed`        | error    | File cannot be parsed. This is a bug of the parser.               |
    | `duplicate-definition`| warning  | Module, interface or package is defined more than once in the project. |
    | `undefined-module`    | warning  | Module of an instance is not defined in the project. `item` is the instance. |
    | `filelist-not-found`  | error    | Filelist cannot be read.                                          |
    | `filelist-unknown`    | warning  | Option of a filelist is not understood.                           |
    | `filelist-variable`   | warning  | Environment variable used by a filelist is not defined.           |
    | `statement-skipped`   | info     | Statement of a process is not understood (a task call).           |

    The macros of the `macro-*` codes are not expanded, the macros of a file of the `include-*` codes are
    unknown. In both cases and on `header-item-skipped`, parameters or ports may be missing.

    Code the parser has no interest in (i.e. `initial` blocks, assertions) is skipped without diagnostic.
    The codes `file-*`, `parse-failed`, `duplicate-definition`, `undefined-module` and `filelist-*` are reported
    by a [Project][hdl_parser.project.Project] only.

    Attributes:
        code: Kind of problem. See table above.
        severity: `error`, `warning` or `info`.
        message: Description.
        loc: Source Location within the parsed file. A problem within an included file points to the
             `` `include `` statement.
        item: Identifier of the related item: the module the problem is located in, if not stated otherwise.
        file: Included file or filelist the problem is located in. Empty, if located in the parsed file itself.
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
    "Signal",
    "Process",
    "Modport",
    "Function",
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
    | Parameter, local parameter, port, signal | `top.WIDTH`          |
    | Signal within labeled generate blocks    | `top.g_a.data`       |
    | Type                                     | `bus_pkg.req_t`      |
    | Function or task, argument               | `bus_pkg.f.arg`      |
    | Process with label, without label        | `top.p_reg`, `top.#always1` |
    | Component (VHDL), its generics and ports | `pkg.comp`, `pkg.comp.clk` |
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
        path: Related File. Within a project, the path is relative to the root of the project.
        lang: Language: `sv` (SystemVerilog) or `vhdl`.
        includes: Paths of the included files, which have been read to expand macros (the file depends on them).
                  Within a project, the paths are relative to the root of the project.
        modules: Modules Within That File.
        interfaces: Interfaces Within That File.
        packages: Packages Within That File.
        diagnostics: Problems found while parsing, in the order of the file.
    """

    path: Path | None
    lang: Literal["sv", "vhdl"] = "sv"
    includes: tuple[str, ...] = ()
    modules: tuple["Module", ...] = ()
    interfaces: tuple["Interface", ...] = ()
    packages: tuple["Package", ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @pyd.field_serializer("path", when_used="json")
    def _serialize_path(self, path: Path | None) -> str | None:
        """A relative path is the same on all platforms: with forward slashes."""
        if path is None or path.is_absolute():
            return None if path is None else str(path)
        return path.as_posix()

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
        units: tuple[Module | Package, ...] = (*self.packages, *self.interfaces, *self.modules)
        for unit in units:
            yield from _iter_unit(unit)

    def find(self, id_: str) -> "Item | None":
        """Item with the identifier `id_`: local (`top.a`) or full (`rtl/top.sv:top.a`). `None` if not found."""
        if ":" in id_:
            # local identifiers never contain a colon, the file part might
            file_id, id_ = id_.rsplit(":", 1)
            if file_id != self.file_id:
                return None
        return next((item for item in self.iter_items() if item.id == id_), None)


def _iter_unit(unit: "Module | Package") -> Iterator["Item"]:
    """`unit` (a module, interface or package) and all its items."""
    yield unit
    yield from unit.params
    yield from unit.localparams
    yield from getattr(unit, "ports", ())
    yield from getattr(unit, "signals", ())
    for typedef in unit.typedefs:
        yield from (typedef, *typedef.members)
    for function in unit.functions:
        yield from (function, *function.args)
    yield from getattr(unit, "processes", ())
    for component in unit.components:
        yield from (component, *component.params, *component.ports)
    yield from getattr(unit, "unresolved_macros", ())
    for modport in getattr(unit, "modports", ()):
        yield from (modport, *modport.ports)
    for inst in getattr(unit, "insts", ()):
        yield from (inst, *inst.params, *inst.connections)


class Module(_BaseModel):
    """Represents a SystemVerilog Module with parameters, ports and submodules.

    Attributes:
        name: Module Name
        params: Parameters
        ports: Ports
        localparams: Local Parameters
        signals: Signals: the nets and variables declared within the module.
        typedefs: Types declared within the module.
        functions: Functions and tasks declared within the module.
        processes: The `always` blocks (VHDL: processes) with their clock and reset.
        assigns: Continuous assignments: `assign`, net declarations with value (`wire x = a & b;`).
                 VHDL: concurrent signal assignments. The assignments of processes are part of the process.
        components: Component declarations (VHDL): modules with name, parameters and ports.
        insts: Submodule Instances.
        ifdefs: Conditions the module is defined at.
        unresolved_macros: Macros used in the module header, which could not be expanded.
                           Ports or parameters defined by these macros are missing.
        imports: Imported names of packages: `my_pkg::*`, `my_pkg::WIDTH`. VHDL: `work.my_pkg.all`.
        partial: VHDL: the entity is not part of this file. This is just the content of an architecture.
        loc: Source Location: from `module` to `endmodule`. VHDL: the entity.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    params: tuple["Param", ...] = ()
    ports: tuple["Port", ...] = ()
    localparams: tuple["Param", ...] = ()
    signals: tuple["Signal", ...] = ()
    typedefs: tuple["Typedef", ...] = ()
    functions: tuple["Function", ...] = ()
    processes: tuple["Process", ...] = ()
    assigns: tuple["Assignment", ...] = ()
    components: tuple["Module", ...] = ()
    insts: tuple["ModuleInstance", ...] = ()
    ifdefs: tuple[str, ...] = ()
    unresolved_macros: tuple["MacroCall", ...] = ()
    imports: tuple[str, ...] = ()
    partial: bool = False
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
    """Represents a SystemVerilog or VHDL Package with parameters, types and functions.

    The constants of a VHDL package are its local parameters.

    Attributes:
        name: Package Name
        params: Parameters
        localparams: Local Parameters
        typedefs: Types
        functions: Functions and tasks (VHDL: procedures)
        components: Component declarations (VHDL): modules with name, parameters and ports.
        imports: Imported names of other packages: `my_pkg::*`, `my_pkg::WIDTH`. VHDL: `work.my_pkg.all`.
        ifdefs: Conditions the package is defined at.
        loc: Source Location: from `package` to `endpackage`.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    params: tuple["Param", ...] = ()
    localparams: tuple["Param", ...] = ()
    typedefs: tuple["Typedef", ...] = ()
    functions: tuple["Function", ...] = ()
    components: tuple["Module", ...] = ()
    imports: tuple[str, ...] = ()
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None


class Function(_BaseModel):
    """Represents the signature of a function or task (VHDL: procedure).

    Attributes:
        name: Name
        kind: `function`, `task` or `procedure`.
        rtype: Return type of a function: `logic`, `int unsigned`, `pkg::t`, `void`. Empty, if not given.
        dim: Dimension (Packed) of the return type.
        args: Arguments, as ports with direction (`input` by default), type, dimensions and default.
        comment: tuple of associated comments
        ifdefs: Conditions the function is defined at.
        loc: Source Location: from `function` to `endfunction`.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    name: str
    kind: Literal["function", "task", "procedure"]
    rtype: str = ""
    dim: str = ""
    args: tuple["Port", ...] = ()
    comment: tuple[str, ...] = ()
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
        ptype: Parameter type ('integer', 'real', 'string', etc.). VHDL: `constant`, if stated.
        dtype: Data Type: `signed` or `unsigned`. VHDL: the type.
        name: Name of the parameter
        dim: Dimension (Packed)
        dim_unpacked: Unpacked Dimension
        comment: tuple of associated comments
        loc: Source Location of the declaration. Names declared together share it.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    ptype: str = ""
    dtype: str = ""
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
        default: Default value. Empty, if not given.
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
    default: str = ""
    ifdefs: tuple[str, ...] = ()
    comment: tuple[str, ...] = ()
    loc: Location | None = None


class Signal(_BaseModel):
    """Represents a net or variable declared within a module: `logic [7:0] data_q;`.

    Variables of functions, tasks and procedural code are no signals of the module.

    Attributes:
        ptype: Type: `logic`, `wire`, `reg`, `my_pkg::my_t`, `enum`, `struct`, ...
        dtype: Data Type: `signed` or `unsigned`. VHDL: the type.
        name: Name of the signal
        dim: Dimension (Packed)
        dim_unpacked: Unpacked Dimension
        default: Initial value, or the expression assigned to a net. Empty, if not given.
        generates: Generate constructs the signal is declared in, from the outermost to the innermost.
        ifdefs: Conditions the signal is declared at.
        comment: tuple of associated comments
        loc: Source Location of the declaration. Names declared together share it.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
    """

    id: str = ""
    ptype: str = ""
    dtype: str = ""
    name: str
    dim: str = ""
    dim_unpacked: str = ""
    default: str = ""
    generates: tuple["Generate", ...] = ()
    ifdefs: tuple[str, ...] = ()
    comment: tuple[str, ...] = ()
    loc: Location | None = None


class Event(_BaseModel):
    """One entry of a sensitivity list: `posedge clk_i`.

    Attributes:
        edge: `posedge`, `negedge` or `edge`. Empty for a level sensitive signal.
        signal: The signal.
    """

    edge: Literal["posedge", "negedge", "edge", ""] = ""
    signal: str


class Process(_BaseModel):
    """Represents an `always` block (VHDL: a process), with its clock and reset.

    | Code                                                       | `clock`  | `reset`   |
    | ---------------------------------------------------------- | -------- | --------- |
    | `always_ff @(posedge clk_i)`                               | `clk_i`  |           |
    | `always_ff @(posedge clk_i or negedge rst_ni) if (!rst_ni)`| `clk_i`  | `rst_ni`  |
    | `always_comb`, `always @*`, `always @(a or b)`             |          |           |
    | `process (clk) ... if rising_edge(clk)` (VHDL)             | `clk`    |           |

    Clock and reset are never guessed. The reset is the edge of the sensitivity list, which is checked by the
    leading `if` of the block. The clock is the one other edge. Both are empty, if this does not apply. A reset
    which is not part of the sensitivity list (a synchronous one) cannot be told from any other condition, and is
    therefore not reported.

    Attributes:
        name: Label of the block: `begin : name`. VHDL: the label of the process. Empty, if there is none.
        kind: `always`, `always_ff`, `always_comb`, `always_latch` or `process` (VHDL).
        events: Sensitivity list. Empty for `always_comb`, `always_latch` and `@*`.
        clock: Clock signal. Empty, if there is none or it is not known.
        clock_edge: Active edge of the clock: `posedge` or `negedge`.
        reset: Asynchronous reset signal. Empty, if there is none or it is not known.
        reset_edge: Edge the reset gets active at: `negedge` for an active low reset.
        generates: Generate constructs the block is located in, from the outermost to the innermost.
        assigns: The assignments within the block, in the order of the code.
        comment: tuple of associated comments
        ifdefs: Conditions the block is defined at.
        loc: Source Location of the whole block.
        id: Identifier, unique within the file. See [hdl_parser.datamodel.File][].
            Blocks without label are numbered. This number changes, if a block is added in front.
    """

    id: str = ""
    name: str = ""
    kind: Literal["always", "always_ff", "always_comb", "always_latch", "process"]
    events: tuple[Event, ...] = ()
    clock: str = ""
    clock_edge: str = ""
    reset: str = ""
    reset_edge: str = ""
    generates: tuple["Generate", ...] = ()
    assigns: tuple["Assignment", ...] = ()
    comment: tuple[str, ...] = ()
    ifdefs: tuple[str, ...] = ()
    loc: Location | None = None


class Assignment(_BaseModel):
    """One Assignment: Of A Signal, By A Continuous Assignment Or Within A Process.

    | Code                                     | `target` | `select` | `reads`      | `conds`    |
    | ---------------------------------------- | -------- | -------- | ------------ | ---------- |
    | `assign y = a & b;`                      | `y`      |          | `a`, `b`     |            |
    | `if (en) q[idx] <= d;`                   | `q`      | `[idx]`  | `idx`, `d`   | `en`       |
    | `{c, s} = x + y;`                        | `c`, `s` (two assignments) | | `x`, `y` |          |
    | `y <= a when sel = '1' else b;` (VHDL)   | `y`      |          | `a`, `b`, `sel` |         |

    The names read are the signals, ports and variables used by the expression, and by the selects of the target.
    Parameters, enumeration members, functions and packages are left out, as far as they are declared in the
    module. Members of structs and interfaces stand for their base: `bus.req` reads `bus`.

    Attributes:
        target: Name of the assigned signal, port or variable. A concatenation of targets is split.
        select: Select of the target, as written: `[3:0]`, `.field`, `(7 downto 0)`. Empty for the whole target.
        reads: Names read by the assigned value.
        conds: Names read by the conditions the assignment is located in: `if`, `case`, loops (control).
        blocking: Blocking assignment (`=`, VHDL `:=`, any continuous assignment). `False` for `<=` within a
                  process.
        generates: Generate constructs a continuous assignment is located in, from the outermost to the innermost.
                   The ones of an assignment within a process are the ones of the process.
        ifdefs: Conditions the assignment is made at.
        loc: Source Location of the assignment.
    """

    target: str
    select: str = ""
    reads: tuple[str, ...] = ()
    conds: tuple[str, ...] = ()
    blocking: bool = True
    generates: tuple["Generate", ...] = ()
    ifdefs: tuple[str, ...] = ()
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
    | `else if (B) begin : g_b`         | `elsif B generate`                 | `if`   | `g_b`  | `B`         |
    | `else begin : g_c`                | `else generate`                    | `else` | `g_c`  |             |
    | `for (i = 0; i < N; i++) begin`   | `g : for i in 0 to N-1 generate`   | `for`  |        | `i = 0; ...`|
    | `case (W)`                        | `g : case W generate`              | `case` |        | `W`         |
    | `begin : g_d` (i.e. a case item)  |                                    | `begin`| `g_d`  |             |
    |                                   | `b : block`                        | `block`| `b`    |             |

    An instance within a `for` is created multiple times. VHDL: the alternatives of an `if` share its label.

    Attributes:
        kind: Kind of construct. See table above.
        name: Label. Empty for blocks without label, and constructs without `begin`.
        cond: Condition of `if`, loop of `for` or expression of `case`.
        others: Alternatives (`else`, `else if`): the conditions of the alternatives in front, which are not
                met: `A` for `g_b`, `A` and `B` for `g_c`.
    """

    kind: GenerateKind
    name: str = ""
    cond: str = ""
    others: tuple[str, ...] = ()


class ModuleInstance(_BaseModel):
    """Represents An Instance Of A Module Within Another Module.

    Attributes:
        name: Module Instance Name
        module: Module Name
        dim: Dimension of an array of instances: `[3:0]`.
        params: Parameter values: `#(.WIDTH(8))`, or `generic map (WIDTH => 8)` in VHDL.
        connections: Connections
        wildcard: The ports which are not connected otherwise are connected by name: `.*`.
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
    wildcard: bool = False
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


class Settings(_BaseModel):
    """How The Files Of A Project Are Parsed.

    Attributes:
        expand_macros: Macros with known definition are expanded.
        resolve_ifdefs: `` `ifdef `` conditions on macros which are known to be defined are resolved.
        defines: Macros defined for all files, by name. Used by `expand_macros` only.
        inc_dirs: Include directories, relative to the root of the project if located there.
        lib_dirs: Library directories: a module which is not defined is searched for as `<lib_dir>/<module><lib_ext>`.
        lib_exts: Extensions of the files within library directories.
    """

    expand_macros: bool = False
    resolve_ifdefs: bool = False
    defines: dict[str, str] = {}
    inc_dirs: tuple[str, ...] = ()
    lib_dirs: tuple[str, ...] = ()
    lib_exts: tuple[str, ...] = ()


class Value(_BaseModel):
    """Value Of An Expression, Within One Instance.

    Nothing is ever guessed: an expression which cannot be evaluated for sure has no `value`, and `unknown`
    tells the reason.

    Attributes:
        expr: The expression, as written: `$clog2(DEPTH) + 1`. For a port: its type and dimensions.
        value: The value. For a port: its number of bits. `None`, if it is not known.
        unknown: Why the value is not known: `'DEPTH' is not known`, `function 'f' is not evaluated`.
    """

    expr: str = ""
    value: int | float | str | bool | None = None
    unknown: str = ""


class HierarchyNode(_BaseModel):
    """One Instance Within The Hierarchy Of A Project, Or Its Top.

    Attributes:
        name: Name of the instance. Name of the module for the top.
        module: Name of the module.
        inst: Full identifier of the instance (`rtl/top.sv:top.u_sub`). Empty for the top.
        definition: Full identifier of the module (`rtl/sub.sv:sub`). Empty, if it is not defined in the project.
        multiple: The instance is created multiple times: it is an array, or located in a `for` generate.
        children: The instances within the module.
        truncated: The instances within are left out: the depth limit is reached, or the module contains itself.
        params: Values of the parameters and local parameters of this instance, by name. Just set by
                [Project.elaborate][hdl_parser.project.Project.elaborate].
        ports: Number of bits of the ports of this instance, by name. Just set by
               [Project.elaborate][hdl_parser.project.Project.elaborate].
    """

    name: str
    module: str
    inst: str = ""
    definition: str = ""
    multiple: bool = False
    children: tuple["HierarchyNode", ...] = ()
    truncated: bool = False
    params: dict[str, Value] = {}
    ports: dict[str, Value] = {}


class Use(_BaseModel):
    """One Place A Module Is Instantiated At.

    Attributes:
        inst: Full identifier of the instance (`rtl/top.sv:top.u_sub`).
        module: Full identifier of the module the instance is located in (`rtl/top.sv:top`).
        loc: Source Location of the instance within its file.
    """

    inst: str
    module: str
    loc: Location | None = None


LinkKind: TypeAlias = Literal["assign", "comb", "ff", "latch", "inst", "port", "unknown"]
"""Kind Of A Driver Or Load."""


class Link(_BaseModel):
    """One Driver Or Load Of A Signal, Within The Hierarchy Below A Top.

    | `kind`    | Driver                                    | Load                                        |
    | --------- | ----------------------------------------- | ------------------------------------------- |
    | `assign`  | continuous assignment                     | continuous assignment reading the signal    |
    | `comb`    | assignment of a combinational process     | ... reading the signal                      |
    | `ff`      | assignment of a clocked process           | ... reading the signal, or clocked by it    |
    | `latch`   | assignment of `always_latch`              | ... reading the signal                      |
    | `inst`    | output port of an instance                | input port of an instance                   |
    | `port`    | input port: the connection of the parent  | output port: the connection of the parent   |
    | `unknown` | pin of an instance of an unknown module   | pin of an instance of an unknown module     |

    Attributes:
        kind: See table above.
        nets: Instance paths of the signals on the other side: the ones read by a driver, the ones driven by a load.
        conds: Driver: instance paths of the signals read by the conditions around (`if`, `case`).
        clock: Instance path of the clock of a flip-flop. Empty, if not known.
        control: Load: the signal is read by a condition or as clock only.
        select: Select of the driven signal, as written: `[3:0]`. Empty for the whole signal.
        item: Full identifier of the process, the instance or the module (continuous assignment).
        external: A port of the top: driven or loaded outside of the design.
        multiple: The instance is created multiple times (array or `for` generate), which are not told apart.
        unknown: Why the other side is not known: i.e. the module is not defined in the project.
        file: File of `loc`.
        loc: Source Location of the assignment or connection.
    """

    kind: LinkKind
    nets: tuple[str, ...] = ()
    conds: tuple[str, ...] = ()
    clock: str = ""
    control: bool = False
    select: str = ""
    item: str = ""
    external: bool = False
    multiple: bool = False
    unknown: str = ""
    file: str = ""
    loc: Location | None = None


class Hop(_BaseModel):
    """One Signal Of A Trace, With The Load Reaching It From The One In Front.

    Attributes:
        net: Instance path of the signal.
        kind: Kind of the load reaching it (see [Link][hdl_parser.datamodel.Link]). Empty for the first one.
        control: The signal in front is read by a condition or as clock only.
        select: Select of this signal, as driven: `[3:0]`.
        item: Full identifier of the process, instance or module of the load.
        file: File of `loc`.
        loc: Source Location of the assignment or connection.
    """

    net: str
    kind: LinkKind | Literal[""] = ""
    control: bool = False
    select: str = ""
    item: str = ""
    file: str = ""
    loc: Location | None = None
