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

"""Connectivity: Drivers And Loads Of Signals, Across The Hierarchy.

A [Graph][hdl_parser._conn.Graph] is the net graph of one module: its nets (ports, signals and the variables of
processes) and the statements, which drive and load them: assignments and the pins of instances. It is created
once per module and kept by the project.

[Connectivity][hdl_parser._conn.Connectivity] walks the hierarchy below a top, with the parameter values of every
instance: generate constructs whose condition is false are left out. A signal is addressed by its instance path:
`top.u_core.u_alu.result_o`. Labels of generate blocks are part of the path (`top.g_a.u_sub.x`).

Labeled `for` generate constructs are unrolled on demand: `top.g_st[1].data` is the signal `data` of the second
iteration, and the iterations are told apart all along (`g_st[0].data` does not reach `g_st[1].u_sub`). The
index is checked against the range of the loop. Without an index (`top.g_st.data`), the path stands for all
iterations, which are marked by `multiple`. Instance arrays and unlabeled loops are not unrolled: they are
`multiple` too.

A key of a net within a module is its hierarchical name, with the index of every loop it is located in, if
known: `g_st[1].data`. The base key (`g_st.data`) is the one of the graph.

The granularity is the whole signal. The select of an assignment (`a[3:0]`) is kept as text.

Cells, which pass their input on to their output, are followed by `trace`: modules given as `passthrough`, and
modules with one input and one output, whose output has no driver but blackboxes (wrappers of technology cells).
"""

import heapq
import re
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any, NamedTuple

from . import _refs
from . import datamodel as dm
from ._elab import Elaboration, Scope
from ._expr import Num, Unknown, evaluate

if TYPE_CHECKING:
    from .project import Definition, Project

_DIRECTIONS = {
    "input": "input",
    "in": "input",
    "output": "output",
    "out": "output",
    "buffer": "output",
    "inout": "inout",
    "linkage": "inout",
    "ref": "inout",
}
_INDEX = re.compile(r"\[[^\]]*\]|\([^)]*\)")
# one step of a path or key: name and indices
_PART = re.compile(r"(?P<name>[^\[\]()]*)(?P<index>(?:\[[^\]]*\]|\([^)]*\))*)")
_FORMAL = re.compile(r"\s*([\w$]+)")
_IDENTIFIER = re.compile(r"[a-zA-Z_][\w$]*")
_SV_INIT = re.compile(r"\s*(?:genvar\s+)?(?:int(?:eger)?\s+)?([a-zA-Z_][\w$]*)\s*=\s*(.+)", re.DOTALL)
_VHDL_RANGE = re.compile(r"\s*([a-zA-Z]\w*)\s+in\s+(.+?)\s+(to|downto)\s+(.+)", re.DOTALL | re.IGNORECASE)
_DIM = re.compile(r"\[([^:\]]+)(?::([^\]]+))?\]")
_MAX_NODES = 200_000
_MAX_ITERATIONS = 65_536
# The iterations a driver or load is unrolled to, at most
_MAX_UNROLL = 1024
# A step by a condition counts as this many steps by data
_CONTROL_COST = 1000
_MAX_STOPS = 10

Context = dict[str, int]
"""Index of every loop (by the base key of its label path: `g_st`, `g_st.g_in`), as far as known."""


class PathError(ValueError):
    """An Instance Path Does Not Exist. `suggestions` are similar names, which exist."""

    def __init__(self, message: str, suggestions: tuple[str, ...] = ()):
        super().__init__(message)
        self.message = message
        self.suggestions = suggestions


class Net(NamedTuple):
    """One Net Of A Module.

    Attributes:
        name: Hierarchical name within the module, as written: `data`, `g_a.data`, `p_reg.v` (a variable).
        kind: `port`, `signal`, `variable` (of a process) or `implicit` (assigned, but never declared).
        direction: Direction of a port: `input`, `output` or `inout`.
        file: File of the declaration.
        item: Port or signal. `None` for variables and implicit nets.
        unrolled: It is located in `for` generate constructs, which all have a label.
    """

    name: str
    kind: str
    direction: str = ""
    file: dm.File | None = None
    item: dm.Port | dm.Signal | None = None
    unrolled: bool = True


class Assign(NamedTuple):
    """One Assignment Of A Module, With The Nets It Reads And Drives.

    Attributes:
        dst: Key of the driven net.
        reads: Keys of the nets read by the value.
        conds: Keys of the nets read by the conditions around, and the clock of a flip-flop.
        kind: `assign` (continuous), `comb`, `ff` or `latch`.
        clock: Key of the clock of a flip-flop. Empty, if not known.
        file: File of the assignment.
        assign: The assignment.
        process: The process the assignment is located in. `None` for a continuous assignment.

    A key of a reference into a generate block keeps the index as written: `g_st[0].data`, `g_st[i].data`.
    """

    dst: str
    reads: tuple[str, ...]
    conds: tuple[str, ...]
    kind: str
    clock: str
    file: dm.File
    assign: dm.Assignment
    process: dm.Process | None

    @property
    def generates(self) -> tuple[dm.Generate, ...]:
        return self.process.generates if self.process else self.assign.generates


class Pin(NamedTuple):
    """One Connection Of An Instance, With The Nets Of The Module.

    Attributes:
        name: Hierarchical name of the instance within the module: `u_sub`, `g_a.u_sub`.
        file: File of the instance.
        inst: The instance.
        child: Definition of the instantiated module. `None`, if not defined in the project.
        port: Name of the port of `child`. Empty, if not known.
        direction: Direction of the port: `input`, `output`, `inout` or `unknown`.
        reads: Keys of the nets read by the connection.
        writes: Keys of the nets driven by the connection, with their select.
        con: The connection. `None` for a connection by `.*`.
        formal: Name of the port, as written by a connection by name.
        read_selects: Keys of the nets read by the connection, with their select, as far as the connection is a
                      name with a select or a concatenation of them: `x[4*i+:4]`.
    """

    name: str
    file: dm.File
    inst: dm.ModuleInstance
    child: "Definition | None"
    port: str
    direction: str
    reads: tuple[str, ...]
    writes: tuple[tuple[str, str], ...]
    con: dm.Connection | None
    formal: str = ""
    read_selects: tuple[tuple[str, str], ...] = ()

    @property
    def generates(self) -> tuple[dm.Generate, ...]:
        return self.inst.generates


Driver = Assign | Pin


def base_key(key: str) -> str:
    """Key without indices: `g.data` of `g[0].data`."""
    return _INDEX.sub("", key)


def _parts(key: str) -> list[tuple[str, str]]:
    """Steps of `key` with their indices, as written: `[("g", "[0]"), ("data", "")]`."""
    result = []
    for part in key.split("."):
        mat = _PART.fullmatch(part)
        result.append((mat.group("name"), mat.group("index")) if mat else (part, ""))
    return result


def _context(key: str) -> Context:
    """Indices of the loops of the key `key`: `{"g": 0}` of `g[0].data`."""
    ctx: Context = {}
    prefix: list[str] = []
    for name, index in _parts(key):
        prefix.append(name)
        if index[1:-1].lstrip("-").isdigit():
            ctx[".".join(prefix)] = int(index[1:-1])
    return ctx


def _matches(key: str, other: str) -> bool:
    """`key` and `other` may be the same net: no loop has two different indices."""
    if base_key(key) != base_key(other):
        return False
    ctx = _context(other)
    return all(ctx.get(path, value) == value for path, value in _context(key).items())


class Graph:
    """Net Graph Of One Module: Nets, With Their Drivers And Loads.

    VHDL names are not case sensitive: the keys of the nets of a VHDL module are lower case.
    `drivers` and `loads` are indexed by the base key.
    """

    def __init__(self, project: "Project", definition: "Definition"):
        self.definition = definition
        self.lang = definition.file.lang
        self.nets: dict[str, Net] = {}
        self.drivers: dict[str, list[Driver]] = {}
        self.loads: dict[str, list[Driver]] = {}
        # labeled `for` generate constructs, by the base key of their label path
        self.loops: dict[str, dm.Generate] = {}
        # instances by the key of their hierarchical name, and their pins
        self.insts: dict[str, tuple[dm.File, dm.ModuleInstance]] = {}
        self.pins: dict[int, list[Pin]] = {}
        # label paths of the loops of the generate constructs, by their id
        self._loop_paths: dict[int, tuple[str, ...]] = {}
        units = [(definition.file, definition.unit), *definition.bodies]
        for file, unit in units:
            self._add_nets(file, unit)
        for file, unit in units:
            self._add_assigns(file, unit)
        for file, inst in definition.insts:
            self._add_pins(project, file, inst)

    def key(self, name: str) -> str:
        """Name as it is looked up."""
        return name.lower() if self.lang == "vhdl" else name

    def resolve(self, name: str, generates: tuple[dm.Generate, ...] = ()) -> str | None:
        """Key of the net `name`, as it is used within the generate blocks `generates`. `None`, if there is none.

        `name` may be a hierarchical reference: `g[0].data` is a net of a generate block, `bus.req` the net `bus`.
        """
        labels = [generate.name for generate in generates if generate.name]
        parts = name.split(".")
        for cut in range(len(parts), 0, -1):
            *front, last = parts[:cut]
            ref = ".".join((*front, _INDEX.sub("", last)))
            stripped = base_key(ref)
            for number in range(len(labels), -1, -1):
                key = self.key(".".join((*labels[:number], stripped)))
                if key in self.nets:
                    return self.key(".".join((*labels[:number], ref)))
        return None

    def loop_paths(self, generates: tuple[dm.Generate, ...]) -> tuple[str, ...]:
        """Base keys of the label paths of the labeled loops of `generates`."""
        found = self._loop_paths.get(id(generates))
        if found is None:
            paths = []
            labels: list[str] = []
            for generate in generates:
                if generate.name:
                    labels.append(generate.name)
                    if generate.kind == "for":
                        paths.append(self.key(".".join(labels)))
            found = self._loop_paths[id(generates)] = tuple(paths)
        return found

    # --- creation ---

    def _add_loops(self, generates: tuple[dm.Generate, ...]) -> bool:
        """Add the loops of `generates`. Return whether all of them have a label."""
        labels: list[str] = []
        unrolled = True
        for generate in generates:
            if generate.name:
                labels.append(generate.name)
                if generate.kind == "for":
                    self.loops.setdefault(self.key(".".join(labels)), generate)
            elif generate.kind == "for":
                unrolled = False
        return unrolled

    def _add_nets(self, file: dm.File, unit: dm.Module | dm.Package) -> None:
        for port in getattr(unit, "ports", ()):
            direction = _DIRECTIONS.get(port.direction, "")
            self.nets.setdefault(self.key(port.name), Net(port.name, "port", direction, file, port))
        for signal in getattr(unit, "signals", ()):
            unrolled = self._add_loops(signal.generates)
            name = ".".join((*(generate.name for generate in signal.generates if generate.name), signal.name))
            self.nets.setdefault(self.key(name), Net(name, "signal", "", file, signal, unrolled))
        for inst in getattr(unit, "insts", ()):
            self._add_loops(inst.generates)
            name = ".".join((*(generate.name for generate in inst.generates if generate.name), inst.name))
            self.insts.setdefault(self.key(name), (file, inst))
        for assign in getattr(unit, "assigns", ()):
            self._add_loops(assign.generates)

    def _add_assigns(self, file: dm.File, unit: dm.Module | dm.Package) -> None:
        for assign in getattr(unit, "assigns", ()):
            self._add_assign(file, assign, None, "assign", "")
        for process in getattr(unit, "processes", ()):
            unrolled = self._add_loops(process.generates)
            kind = _process_kind(process)
            prefix = file.full_id(process).rpartition(":")[2].partition(".")[2]
            # variables: assigned within the process, but no nets of the module
            variables: dict[str, str] = {}
            for assign in process.assigns:
                if self.resolve(assign.target, process.generates) is None:
                    name = f"{prefix}.{assign.target}"
                    key = self.key(name)
                    self.nets.setdefault(key, Net(name, "variable", "", file, unrolled=unrolled))
                    variables[self.key(assign.target)] = key
            clock = self.resolve(process.clock, process.generates) if process.clock and kind == "ff" else None
            for assign in process.assigns:
                dst = variables.get(self.key(assign.target))
                self._add_assign(file, assign, process, "comb" if dst else kind, clock or "", variables)

    def _add_assign(  # noqa: PLR0913
        self,
        file: dm.File,
        assign: dm.Assignment,
        process: dm.Process | None,
        kind: str,
        clock: str,
        variables: dict[str, str] | None = None,
    ) -> None:
        generates = process.generates if process else assign.generates
        local = variables or {}

        def resolve(name: str) -> str | None:
            return local.get(self.key(name)) or self.resolve(name, generates)

        dst = resolve(assign.target)
        if dst is None:
            # Verilog: a net, which is assigned but not declared, is declared implicitly
            dst = self.key(assign.target)
            unrolled = self._add_loops(generates)
            self.nets.setdefault(dst, Net(assign.target, "implicit", "", file, unrolled=unrolled))
        reads = _refs.unique(key for key in map(resolve, assign.reads) if key)
        conds = _refs.unique(key for key in (*map(resolve, assign.conds), clock) if key and key not in reads)
        record = Assign(dst, reads, conds, kind, clock, file, assign, process)
        self.drivers.setdefault(base_key(dst), []).append(record)
        for key in _refs.unique(base_key(key) for key in (*reads, *conds)):
            self.loads.setdefault(key, []).append(record)

    def _add_pins(self, project: "Project", file: dm.File, inst: dm.ModuleInstance) -> None:
        child = project._resolve_inst(file, inst)
        ports = list(getattr(child.unit, "ports", ())) if child else []
        casefold = file.lang == "vhdl" or (child is not None and child.file.lang == "vhdl")
        by_name = {port.name.lower() if casefold else port.name: port for port in ports}
        name = ".".join((*(generate.name for generate in inst.generates if generate.name), inst.name))
        pins: list[Pin] = []
        connected: set[str] = set()
        position = 0
        for con in inst.connections:
            formal = ""
            if con.port:
                mat = _FORMAL.match(con.port)
                formal = mat.group(1) if mat else con.port
                port = by_name.get(formal.lower() if casefold else formal)
            else:
                port = ports[position] if position < len(ports) else None
                position += 1
            if port is not None:
                connected.add(port.name)
            pins.append(self._pin(name, file, inst, child, port, con.con, con, formal))
        if inst.wildcard:
            pins += [
                self._pin(name, file, inst, child, port, port.name, None, port.name)
                for port in ports
                if port.name not in connected and self.resolve(port.name, inst.generates)
            ]
        self.pins[id(inst)] = pins
        for pin in pins:
            for key in _refs.unique(base_key(key) for key, _ in pin.writes):
                self.drivers.setdefault(key, []).append(pin)
            for key in _refs.unique(base_key(key) for key in pin.reads):
                self.loads.setdefault(key, []).append(pin)

    def _pin(  # noqa: PLR0913
        self,
        name: str,
        file: dm.File,
        inst: dm.ModuleInstance,
        child: "Definition | None",
        port: dm.Port | None,
        expr: str,
        con: dm.Connection | None,
        formal: str,
    ) -> Pin:
        direction = _DIRECTIONS.get(port.direction, "unknown") if port and child else "unknown"
        lang = file.lang
        if lang == "sv" and _IDENTIFIER.fullmatch(expr) and self.resolve(expr, inst.generates) is None:
            # Verilog: a net connected to an instance is declared implicitly
            self.nets.setdefault(self.key(expr), Net(expr, "implicit", "", file))
        reads: tuple[str, ...] = ()
        writes: tuple[tuple[str, str], ...] = ()
        read_selects: tuple[tuple[str, str], ...] = ()
        if expr and expr.lower() != "open":
            if direction in ("input", "inout", "unknown"):
                keys = (self.resolve(name, inst.generates) for name in _refs.reads_text(expr, lang, paths=True))
                reads = _refs.unique(key for key in keys if key)
                parts = (
                    (self.resolve(part.name, inst.generates), part.select) for part in _refs.targets_text(expr, lang)
                )
                read_selects = tuple((key, select) for key, select in parts if key)
            if direction in ("output", "inout", "unknown"):
                targets = _refs.targets_text(expr, lang)
                found = ((self.resolve(target.name, inst.generates), target.select) for target in targets)
                writes = tuple((key, select) for key, select in found if key)
        port_name = port.name if port else ""
        return Pin(name, file, inst, child, port_name, direction, reads, writes, con, formal, read_selects)


def _process_kind(process: dm.Process) -> str:
    """`ff`, `latch` or `comb`."""
    if process.kind == "always_ff" or process.clock or any(event.edge for event in process.events):
        return "ff"
    if process.kind == "always_latch":
        return "latch"
    return "comb"


class _Bound:
    """A Scope, With The Values Of Loop Variables (`genvar`)."""

    def __init__(self, scope: Scope, values: dict[str, int]):
        self.scope = scope
        self.lang = scope.lang
        self.values = values

    def __getattr__(self, name: str) -> Any:
        return getattr(self.scope, name)

    def value(self, path: tuple[str, ...]) -> Num:
        if len(path) == 1:
            value = self.values.get(self.scope.key(path[0]))
            if value is not None:
                return Num(value)
        return self.scope.value(path)

    def evaluate(self, expr: str, lang: str | None = None) -> Num:
        return evaluate(expr, lang or self.lang, self)

    def value_of(self, expr: str, lang: str | None = None) -> dm.Value:
        try:
            return dm.Value(expr=expr, value=self.evaluate(expr, lang).value)
        except Unknown as exc:
            return dm.Value(expr=expr, unknown=str(exc))


def _loop_var(generate: dm.Generate, lang: str) -> str:
    """Name of the variable of the loop `generate`. Empty, if not known."""
    mat = _VHDL_RANGE.match(generate.cond) if lang == "vhdl" else _SV_INIT.match(generate.cond.split(";")[0])
    return mat.group(1) if mat else ""


def _loop_step(var: str, text: str) -> str | None:
    """`text`, the step of a loop over `var`, as expression of the next value: `i + 1` of `i++`."""
    text = text.strip()
    if text in (f"{var}++", f"++{var}"):
        return f"{var} + 1"
    if text in (f"{var}--", f"--{var}"):
        return f"{var} - 1"
    mat = re.fullmatch(rf"{re.escape(var)}\s*([-+*/]|<<|>>)?=\s*(.+)", text, re.DOTALL)
    if mat is None:
        return None
    return f"{var} {mat.group(1)} ({mat.group(2)})" if mat.group(1) else mat.group(2)


# --- hierarchy ---


class Inst:
    """One Instance Within The Hierarchy Below A Top.

    Attributes:
        path: Instance path: `top`, `top.u_core`, `top.g_a.u_sub`, `top.g_st[1].u_sub`.
        definition: Its module.
        scope: Values of its parameters.
        parent: Instance it is located in. `None` for the top.
        pin_file: File of the instance within `parent`.
        pin_inst: The instance within `parent`.
        multiple: It, or an instance above, is created multiple times (array, or loop without index).
        ctx: Indices of the loops of `parent` the instance is located in.
    """

    def __init__(  # noqa: PLR0913
        self,
        path: str,
        definition: "Definition",
        scope: Scope,
        parent: "Inst | None" = None,
        pin_file: dm.File | None = None,
        pin_inst: dm.ModuleInstance | None = None,
        multiple: bool = False,
        ctx: Context | None = None,
    ):
        self.path = path
        self.definition = definition
        self.scope = scope
        self.parent = parent
        self.pin_file = pin_file
        self.pin_inst = pin_inst
        self.multiple = multiple
        self.ctx: Context = ctx or {}
        self.children: dict[tuple, Inst | None] = {}
        self.active: dict[tuple, bool | None] = {}
        self.bound: dict[tuple, _Bound] = {}
        self.ranges: dict[tuple, tuple[int, ...] | None] = {}


Node = tuple[Inst, str]
"""A Net Within An Instance: The Instance And The Key Of The Net (with the indices of its loops, if known)."""


class Step(NamedTuple):
    """One Driver Or Load Of A Net.

    Attributes:
        kind: `assign`, `comb`, `ff`, `latch`, `inst` (a pin of an instance), `port` (across a port of the module),
              `passthrough` (across a cell, which passes its input on) or `unknown` (a pin of a module, which is
              not defined).
        nets: The nets on the other side: the ones read by a driver, the ones driven by a load.
        conds: Driver: the nets read by its conditions.
        control: Load: the net is read by a condition (or as clock) only.
        clock: The clock of a flip-flop.
        record: The assignment or pin. `None` for a port of the top, and across a defined pass-through cell.
        inst: The instance the record is located in.
        select: The select of the driven net (the net of a driver, the one of `nets` of a load), as evaluated
                within an iteration of a loop: `[7:4]`. `None`: as written by the record.
        bits: The bits of the net (lowest, highest), which are driven by a driver, read by a load. `None` for the
              whole net, or if not known.
        driven: Load: the bits of the driven net (`nets`). `None` for the whole net, or if not known.
    """

    kind: str
    nets: tuple[Node, ...] = ()
    conds: tuple[Node, ...] = ()
    control: bool = False
    clock: Node | None = None
    record: Driver | None = None
    inst: Inst | None = None
    select: str | None = None
    bits: tuple[int, int] | None = None
    driven: tuple[int, int] | None = None


class Through(NamedTuple):
    """A Cell, Which Passes Its Inputs On To Its Outputs. Empty: all ports (of a module, which is not defined)."""

    inputs: frozenset[str] = frozenset()
    outputs: frozenset[str] = frozenset()


def parse_passthrough(specs: Iterable[str]) -> dict[str, Through]:
    """Pass-through cells by module name: `buf_wrap`, or with ports `BUFX2:A->Y`, `MUX2:A,B,S->Y`."""
    cells: dict[str, Through] = {}
    for spec in specs:
        module, _, ports = spec.partition(":")
        inputs, _, outputs = ports.partition("->")
        if not module.strip() or (ports and not (inputs.strip() and outputs.strip())):
            raise ValueError(f"'{spec}' is no pass-through cell: 'module' or 'module:in1,in2->out'.")
        cells[module.strip()] = Through(
            frozenset(name.strip() for name in inputs.split(",") if name.strip()),
            frozenset(name.strip() for name in outputs.split(",") if name.strip()),
        )
    return cells


class Connectivity:
    """Drivers And Loads Of The Nets Of A Project, With The Parameter Values Of One Top.

    `passthrough`: cells which pass their inputs on to their outputs. See
    [parse_passthrough][hdl_parser._conn.parse_passthrough].
    """

    def __init__(
        self,
        project: "Project",
        params: dict[str, dm.Value] | None = None,
        passthrough: Iterable[str] = (),
    ):
        self.project = project
        self.elab = Elaboration(project)
        self.params = params or {}
        self.passthrough = parse_passthrough(passthrough)
        self.tops: dict[str, Inst] = {}
        self._through: dict[str, Through | None] = {}
        # the loads, the last trace stopped at: blackboxes and flip-flops
        self.stops: list[tuple[Node, Step]] = []
        self.ff_stops = 0

    def graph(self, definition: "Definition") -> Graph:
        return self.project._graph(definition)

    # --- instances ---

    def top(self, name: str) -> Inst | None:
        project = self.project
        definition = project.resolve(name) or project.resolve(name, casefold=True)
        if definition is None:
            return None
        if definition.id not in self.tops:
            scope = self.elab.scope(definition, self.params)
            self.tops[definition.id] = Inst(definition.unit.name, definition, scope)
        return self.tops[definition.id]

    def child(self, parent: Inst, file: dm.File, inst: dm.ModuleInstance, ctx: Context | None = None) -> Inst | None:
        """Instance `inst` within `parent`, in the iteration `ctx` of the loops around.

        `None`, if its module is not defined, or contains itself.
        """
        graph = self.graph(parent.definition)
        loops = graph.loop_paths(inst.generates)
        ctx = {path: value for path, value in (ctx or {}).items() if path in loops}
        ident = (id(inst), *sorted(ctx.items()))
        if ident in parent.children:
            return parent.children[ident]
        definition = self.project._resolve_inst(file, inst)
        child = None
        ancestors = []
        node: Inst | None = parent
        while node is not None:
            ancestors.append(node.definition.id)
            node = node.parent
        if definition is not None and definition.id not in ancestors:
            scope = self.bound(parent, ctx)
            overrides = self.elab.overrides(scope, inst, file.lang, definition)  # type: ignore[arg-type]
            child_scope = self.elab.scope(definition, overrides)
            self.elab.parents[id(child_scope)] = parent.scope
            name, unrolled = self.inst_name(parent, inst, ctx)
            multiple = parent.multiple or bool(inst.dim) or not unrolled
            child = Inst(f"{parent.path}.{name}", definition, child_scope, parent, file, inst, multiple, ctx)
        parent.children[ident] = child
        return child

    def inst_name(self, parent: Inst, inst: dm.ModuleInstance, ctx: Context) -> tuple[str, bool]:
        """Name of `inst` within `parent` in the iteration `ctx`: `g_a[1].u_sub`. And whether all loops are known."""
        graph = self.graph(parent.definition)
        labels: list[str] = []
        names: list[str] = []
        unrolled = True
        for generate in inst.generates:
            if not generate.name:
                unrolled = unrolled and generate.kind != "for"
                continue
            labels.append(generate.name)
            index = ctx.get(graph.key(".".join(labels))) if generate.kind == "for" else None
            names.append(generate.name if index is None else f"{generate.name}[{index}]")
            unrolled = unrolled and (generate.kind != "for" or index is not None)
        return ".".join((*names, inst.name)), unrolled

    def node(self, inst: Inst, depth: int | None, path: tuple[str, ...] = ()) -> dm.HierarchyNode:
        """Elaborated [HierarchyNode][hdl_parser.datamodel.HierarchyNode] of `inst` and the instances within.

        Labeled `for` generate constructs with known indices are unrolled: one node per iteration (`g[1].u_sub`),
        with the parameter values of that iteration. Generate constructs, whose condition is false, are left out.
        """
        definition = inst.definition
        path = (*path, definition.id)
        children: list[dm.HierarchyNode] = []
        truncated = False
        if depth == 0:
            truncated = any(True for _ in definition.insts)
        else:
            below = None if depth is None else depth - 1
            for file, sub in definition.insts:
                children.extend(
                    self._node(inst, file, sub, ctx, below, path)
                    for ctx in self.contexts(inst, sub.generates, {})
                    if self.active(inst, sub.generates, ctx)
                )
        return dm.HierarchyNode(
            name=definition.unit.name,
            module=definition.unit.name,
            definition=definition.id,
            children=tuple(children),
            truncated=truncated,
            params=inst.scope.all_params(),
            ports=inst.scope.all_ports(),
        )

    def _node(  # noqa: PLR0913
        self, parent: Inst, file: dm.File, inst: dm.ModuleInstance, ctx: Context, depth: int | None, path: tuple
    ) -> dm.HierarchyNode:
        name, unrolled = self.inst_name(parent, inst, ctx)
        fields: dict[str, Any] = {"name": name, "module": inst.module, "inst": file.full_id(inst)}
        fields["multiple"] = bool(inst.dim) or not unrolled
        child = self.child(parent, file, inst, ctx)
        if child is None:
            # not defined, or the module contains itself
            definition = self.project._resolve_inst(file, inst)
            return dm.HierarchyNode(
                **fields, definition=definition.id if definition else "", truncated=definition is not None
            )
        return self.node(child, depth, path).model_copy(update=fields)

    def bound(self, inst: Inst, ctx: Context) -> Scope | _Bound:
        """Scope of `inst`, with the values of the variables of the loops `ctx`."""
        if not ctx:
            return inst.scope
        ident = tuple(sorted(ctx.items()))
        if ident not in inst.bound:
            graph = self.graph(inst.definition)
            values = {}
            for path, value in ctx.items():
                generate = graph.loops.get(path)
                var = _loop_var(generate, graph.lang) if generate else ""
                if var:
                    values[graph.key(var)] = value
            inst.bound[ident] = _Bound(inst.scope, values)
        return inst.bound[ident]

    def active(self, inst: Inst, generates: tuple[dm.Generate, ...], ctx: Context | None = None) -> bool:
        """Whether the generate constructs `generates` are created within `inst`. Unknown conditions are."""
        for generate in generates:
            if generate.kind == "if" and generate.cond and self._value(inst, generate.cond, ctx) is False:
                return False
            if any(self._value(inst, other, ctx) is True for other in generate.others):
                # an alternative in front is created instead
                return False
        return True

    def _value(self, inst: Inst, cond: str, ctx: Context | None) -> bool | None:
        """Value of the condition `cond` within `inst`. `None`, if it is not known."""
        ident = (cond, *sorted((ctx or {}).items()))
        if ident not in inst.active:
            value = self.bound(inst, ctx or {}).value_of(cond).value
            inst.active[ident] = None if value is None else bool(value)
        return inst.active[ident]

    def loop_range(self, inst: Inst, path: str, ctx: Context) -> tuple[int, ...] | None:
        """Indices of the loop with the label path `path` within `inst`. `None`, if not known."""
        graph = self.graph(inst.definition)
        generate = graph.loops[path]
        outer = {other: value for other, value in ctx.items() if other != path and path.startswith(f"{other}.")}
        ident = (path, *sorted(outer.items()))
        if ident not in inst.ranges:
            inst.ranges[ident] = self._range(inst, generate, outer)
        return inst.ranges[ident]

    def _range(self, inst: Inst, generate: dm.Generate, ctx: Context) -> tuple[int, ...] | None:
        scope = self.bound(inst, ctx)
        lang = inst.definition.file.lang
        try:
            if lang == "vhdl":
                mat = _VHDL_RANGE.match(generate.cond)
                if mat is None:
                    return None
                first = int(scope.evaluate(mat.group(2)).value)  # type: ignore[arg-type]
                last = int(scope.evaluate(mat.group(4)).value)  # type: ignore[arg-type]
                found = range(first, last + 1) if mat.group(3).lower() == "to" else range(first, last - 1, -1)
                return tuple(found) if len(found) <= _MAX_ITERATIONS else None
            init, test, step = ([*generate.cond.split(";"), "", ""])[:3]
            mat = _SV_INIT.match(init)
            nxt = _loop_step(mat.group(1), step) if mat else None
            if mat is None or nxt is None or not test.strip():
                return None
            var = scope.key(mat.group(1))
            value = int(scope.evaluate(mat.group(2)).value)  # type: ignore[arg-type]
            values: list[int] = []
            values_by = dict(scope.values) if isinstance(scope, _Bound) else {}
            for _ in range(_MAX_ITERATIONS):
                bound = _Bound(inst.scope, {**values_by, var: value})
                if not bound.evaluate(test).value:
                    return tuple(values)
                values.append(value)
                value = int(bound.evaluate(nxt).value)  # type: ignore[arg-type]
        except (Unknown, TypeError, ValueError, ZeroDivisionError):
            return None
        return None

    def locate(self, path: str) -> Node:
        """The net with the instance path `path`: `top.u_core.result_o`. Raises `PathError`."""
        file_id, local = _split_file(path)
        top_name, *rest = local.split(".")
        if file_id:
            top_name = f"{file_id}:{top_name}"
        steps = [_parts(step.strip())[0] for step in rest]
        top_name = _INDEX.sub("", top_name)
        inst = self.top(top_name)
        if inst is None:
            raise PathError(f"'{top_name}' is no module of the project.", self._similar_units(top_name))
        if not steps:
            raise PathError(f"'{path}' names a module, but no signal.")
        index = 0
        while True:
            graph = self.graph(inst.definition)
            for end in range(len(steps) - 1, index, -1):
                found = graph.insts.get(graph.key(".".join(name for name, _ in steps[index:end])))
                if found is not None:
                    ctx = self._path_context(inst, steps[index:end], found[1])
                    child = self.child(inst, *found, ctx)
                    if child is None:
                        module = found[1].module
                        name = ".".join(name for name, _ in steps[index:end])
                        raise PathError(f"module '{module}' of '{inst.path}.{name}' is not known.")
                    inst = child
                    index = end
                    break
            else:
                names = [name for name, _ in steps[index:]]
                key = graph.key(".".join(names))
                if key not in graph.nets:
                    raise self._missing(inst, graph, names)
                # the index of the signal itself is a select
                ctx = self._path_context(inst, steps[index:-1])
                return inst, self.concrete(inst, key, ctx)

    def _path_context(
        self, inst: Inst, steps: list[tuple[str, str]], target: dm.ModuleInstance | None = None
    ) -> Context:
        """Indices of the loops given by `steps`, the labels (and the instance `target`) within `inst`."""
        graph = self.graph(inst.definition)
        ctx: Context = {}
        labels: list[str] = []
        for number, (name, index) in enumerate(steps):
            labels.append(name)
            if not index:
                continue
            label = ".".join(labels)
            key = graph.key(label)
            first = index[1 : _INDEX.match(index).end() - 1]  # type: ignore[union-attr]
            if key in graph.loops:
                value = self._index(self.bound(inst, ctx), first)
                if value is None:
                    continue
                found = self.loop_range(inst, key, ctx)
                if found is not None and value not in found:
                    span = f"{min(found)}..{max(found)}" if found else "none"
                    raise PathError(f"'{inst.path}.{label}' has no index {value}: the indices are {span}.")
                ctx[key] = value
            elif target is not None and number == len(steps) - 1:
                self._check_array(inst, target, label, first)
            else:
                raise PathError(f"'{inst.path}.{label}' is no loop or instance array: it has no index.")
        return ctx

    def _check_array(self, inst: Inst, target: dm.ModuleInstance, label: str, first: str) -> None:
        if not target.dim:
            raise PathError(f"'{inst.path}.{label}' is no instance array: it has no index.")
        value = self._index(inst.scope, first)
        mat = _DIM.match(target.dim)
        if value is None or mat is None:
            return
        bounds = [self._index(inst.scope, mat.group(1)), self._index(inst.scope, mat.group(2) or "")]
        if bounds[0] is None or (mat.group(2) and bounds[1] is None):
            return
        low, high = (0, bounds[0] - 1) if not mat.group(2) else sorted(bounds)  # type: ignore[type-var]
        if not low <= value <= high:  # type: ignore[operator]
            raise PathError(f"'{inst.path}.{label}' has no index {value}: the indices are {low}..{high}.")

    @staticmethod
    def _index(scope: Scope | _Bound, text: str) -> int | None:
        if not text.strip():
            return None
        try:
            return int(scope.evaluate(text).value)  # type: ignore[arg-type]
        except (Unknown, TypeError, ValueError, ZeroDivisionError):
            return None

    def _missing(self, inst: Inst, graph: Graph, names: list[str]) -> PathError:
        """Error: `names` is no net within `inst`. Names the first step, which does not exist."""
        keys = [*graph.nets, *graph.insts]
        for number in range(1, len(names)):
            prefix = graph.key(".".join(names[:number]))
            if not any(key.startswith(f"{prefix}.") for key in keys):
                label = ".".join(names[:number])
                inner = {key.rpartition(".")[0] for key in keys if "." in key}
                choices = [
                    name
                    for name in (*(item[1].name for item in graph.insts.values()), *inner)
                    if name.count(".") == number - 1
                ]
                return PathError(
                    f"'{inst.path}' has no instance or generate block '{label}'.", _similar(label, choices)
                )
        name = ".".join(names)
        choices = [net.name for net in graph.nets.values()] + [found[1].name for found in graph.insts.values()]
        return PathError(f"'{inst.path}' has no signal '{name}'.", _similar(name, choices))

    def _similar_units(self, name: str) -> tuple[str, ...]:
        names = [definition.unit.name for definition in self.project._all_modules]
        return _similar(name.rpartition(":")[2], names)

    # --- keys ---

    def concrete(self, inst: Inst, key: str, ctx: Context) -> str:
        """The key `key` (of a record) within the iteration `ctx`: `g[1].data` of `g.data` with `{"g": 1}`.

        An index written by the record (`g[0].data`, `g[i + 1].data`) is evaluated.
        """
        graph = self.graph(inst.definition)
        result = []
        labels: list[str] = []
        for name, index in _parts(key):
            labels.append(name)
            label = ".".join(labels)
            if label not in graph.loops:
                result.append(name)
                continue
            value = ctx.get(label)
            if index:
                text = index[1 : _INDEX.match(index).end() - 1]  # type: ignore[union-attr]
                value = self._index(self.bound(inst, ctx), text)
            result.append(name if value is None else f"{name}[{value}]")
        return ".".join(result)

    def _record_context(self, inst: Inst, record: Driver, key: str) -> Context:
        """Indices of the loops of `record`, given by the net `key` of the same iteration."""
        loops = self.graph(inst.definition).loop_paths(record.generates)
        return {path: value for path, value in _context(key).items() if path in loops}

    def net(self, node: Node) -> Net:
        inst, key = node
        return self.graph(inst.definition).nets[base_key(key)]

    def path(self, node: Node) -> str:
        """Instance path of `node`, with the indices of its loops."""
        names = self.net(node).name.split(".")
        parts = _parts(node[1])
        if len(parts) == len(names):
            names = [name + index for name, (_, index) in zip(names, parts, strict=True)]
        return f"{node[0].path}.{'.'.join(names)}"

    def multiple(self, node: Node) -> bool:
        """`node` stands for multiple nets: of an instance array, or of the iterations of a loop."""
        inst, key = node
        if inst.multiple:
            return True
        net = self.net(node)
        if not net.unrolled:
            return True
        graph = self.graph(inst.definition)
        ctx = _context(key)
        base = base_key(key)
        return any(base.startswith(f"{path}.") and path not in ctx for path in graph.loops)

    # --- drivers and loads ---

    def drivers(self, node: Node, bits: tuple[int, int] | None = None) -> Iterator[Step]:
        """Drivers of the net `node`. With `bits` (lowest, highest), only those which may drive one of them.

        A select within a `for` generate is evaluated per iteration: one step per distinct select.
        """
        inst, key = node
        graph = self.graph(inst.definition)
        steps: list[Step] = []
        for record in graph.drivers.get(base_key(key), ()):
            ctxs = self._iterations(inst, record, self._record_context(inst, record, key))
            ctxs = [ctx for ctx in ctxs if self.active(inst, record.generates, ctx)]
            if isinstance(record, Assign):
                ctxs = [ctx for ctx in ctxs if _matches(self.concrete(inst, record.dst, ctx), key)]
                found = [self._assign_step(inst, record, ctx) for ctx in ctxs]
            else:
                ctxs = [
                    ctx
                    for ctx in ctxs
                    if any(_matches(self.concrete(inst, write, ctx), key) for write, _ in record.writes)
                ]
                select = next((select for write, select in record.writes if _matches(write, key)), "")
                found = [self._pin_step(inst, record, ctx, driver=True) for ctx in ctxs]
                found = [self._selected(inst, record, step, ctx, select) for step, ctx in zip(found, ctxs, strict=True)]
            steps += _merge(found)
        yield from (step for step in steps if _overlaps(step.bits, bits))
        net = graph.nets[base_key(key)]
        if net.kind == "port" and net.direction in ("input", "inout"):
            yield from self._across(inst, net, reads=True)
        if net.kind == "port" and net.direction in ("output", "inout"):
            yield from self._cell(inst, net, driver=True)

    def loads(self, node: Node, bits: tuple[int, int] | None = None) -> Iterator[Step]:
        """Loads of the net `node`. With `bits` (lowest, highest), only those which may read one of them.

        A select within a `for` generate is evaluated per iteration: one step per distinct select.
        """
        inst, key = node
        graph = self.graph(inst.definition)
        base = base_key(key)
        steps: list[Step] = []
        for record in graph.loads.get(base, ()):
            ctxs = self._iterations(inst, record, self._record_context(inst, record, key))
            ctxs = [ctx for ctx in ctxs if self.active(inst, record.generates, ctx)]
            found: list[Step] = []
            if isinstance(record, Assign):
                reads = [read for read in record.reads if base_key(read) == base]
                conds = [cond for cond in record.conds if base_key(cond) == base]
                for ctx in ctxs:
                    by_data = any(_matches(self.concrete(inst, read, ctx), key) for read in reads)
                    by_cond = any(_matches(self.concrete(inst, cond, ctx), key) for cond in conds)
                    if by_data or by_cond:
                        dst = (inst, self.concrete(inst, record.dst, ctx))
                        step = Step(record.kind, (dst,), control=not by_data, record=record, inst=inst)
                        # the select of the driven net
                        step = self._selected(inst, record, step, ctx, record.assign.select)
                        found.append(step._replace(bits=None, driven=step.bits))
            else:
                for ctx in ctxs:
                    if any(_matches(self.concrete(inst, read, ctx), key) for read in record.reads):
                        step = self._pin_step(inst, record, ctx, driver=False)
                        select = next((select for read, select in record.read_selects if _matches(read, key)), "")
                        # the bits read of the net
                        found.append(self._selected(inst, record, step, ctx, select)._replace(select=None))
            steps += _merge(found)
        yield from (step for step in steps if _overlaps(step.bits, bits))
        net = graph.nets[base]
        if net.kind == "port" and net.direction in ("output", "inout"):
            yield from self._across(inst, net, reads=False)
        if net.kind == "port" and net.direction in ("input", "inout"):
            yield from self._cell(inst, net, driver=False)

    def _assign_step(self, inst: Inst, record: Assign, ctx: Context) -> Step:
        """Step of the assignment `record` within the iteration `ctx`."""
        nets = tuple((inst, self.concrete(inst, read, ctx)) for read in record.reads)
        conds = tuple((inst, self.concrete(inst, cond, ctx)) for cond in record.conds)
        clock = (inst, self.concrete(inst, record.clock, ctx)) if record.clock else None
        step = Step(record.kind, nets, conds, clock=clock, record=record, inst=inst)
        return self._selected(inst, record, step, ctx, record.assign.select)

    def _selected(self, inst: Inst, record: Driver, step: Step, ctx: Context, select: str) -> Step:
        """`step` with the bits driven by `select`, and the select as evaluated within a loop."""
        if not select:
            return step
        found = _select(self.bound(inst, ctx), select, inst.definition.file.lang)
        if found is None:
            return step
        low, high, text = found
        looped = bool(self.graph(inst.definition).loop_paths(record.generates))
        return step._replace(bits=(low, high), select=text if looped else None)

    @staticmethod
    def path_select(path: str) -> str:
        """Select of the signal of the instance path `path`, as written: `[5]` of `top.data[5]`."""
        return _parts(_split_file(path)[1].split(".")[-1].strip())[-1][1]

    def select_bits(self, node: Node, select: str) -> tuple[int, int] | None:
        """Bits (lowest, highest) selected by `select` of the net `node`. `None`, if not known."""
        inst, key = node
        found = _select(self.bound(inst, _context(key)), select, inst.definition.file.lang) if select else None
        return found[:2] if found else None

    def _iterations(self, inst: Inst, record: Driver, ctx: Context) -> list[Context]:
        """The iterations of the loops of `record`, which are not given by `ctx`: one context each."""
        return self.contexts(inst, record.generates, ctx)

    def contexts(self, inst: Inst, generates: tuple[dm.Generate, ...], ctx: Context) -> list[Context]:
        """The iterations of the loops of `generates` within `inst`, which are not given by `ctx`: one context each.

        A loop whose range is not known is left without index, as are all, if there are too many iterations.
        """
        found = [ctx]
        for path in self.graph(inst.definition).loop_paths(generates):
            if path in ctx:
                continue
            expanded = []
            for current in found:
                indices = self.loop_range(inst, path, current)
                if indices is None:
                    expanded.append(current)
                else:
                    expanded += [{**current, path: index} for index in indices]
            if len(expanded) > _MAX_UNROLL:
                return [ctx]
            found = expanded
        return found

    def _pin_step(self, inst: Inst, pin: Pin, ctx: Context, driver: bool) -> Step:
        """Step across the pin `pin` of an instance within `inst`: into the instance."""
        child = self.child(inst, pin.file, pin.inst, ctx)
        if child is not None and pin.port:
            port = self.graph(child.definition).key(pin.port)
            return Step("inst", ((child, port),), record=pin, inst=inst)
        cell = self.passthrough.get(pin.inst.module) if child is None else None
        if cell is not None:
            # a pass-through cell, which is not defined: across to the pins on the other side
            mine = (cell.outputs if driver else cell.inputs) if cell.inputs else frozenset()
            others = (cell.inputs if driver else cell.outputs) if cell.inputs else frozenset()
            if not mine or pin.formal in mine:
                nets = []
                for other in self.graph(inst.definition).pins.get(id(pin.inst), ()):
                    if other is pin or (others and other.formal not in others):
                        continue
                    keys = other.reads if driver else tuple(write for write, _ in other.writes)
                    nets += [(inst, self.concrete(inst, key, ctx)) for key in keys]
                return Step("passthrough", tuple(dict.fromkeys(nets)), record=pin, inst=inst)
        return Step("unknown", record=pin, inst=inst)

    def _across(self, inst: Inst, net: Net, reads: bool) -> Iterator[Step]:
        """The nets connected to the port `net` of `inst` within its parent: the ones read or the ones written."""
        parent = inst.parent
        if parent is None or inst.pin_inst is None:
            yield Step("port")
            return
        graph = self.graph(parent.definition)
        key = self.graph(inst.definition).key
        for pin in graph.pins.get(id(inst.pin_inst), ()):
            if pin.port and key(pin.port) == key(net.name):
                nets = pin.reads if reads else tuple(key for key, _ in pin.writes)
                others = tuple((parent, self.concrete(parent, other, inst.ctx)) for other in nets)
                step = Step("port", others, record=pin, inst=parent)
                if not reads and len(pin.writes) == 1:
                    # the select of the driven net within the parent
                    step = self._selected(parent, pin, step, inst.ctx, pin.writes[0][1])
                    step = step._replace(bits=None, driven=step.bits)
                yield step

    def through(self, definition: "Definition") -> Through | None:
        """`definition` as pass-through cell. `None`, if it is none."""
        if definition.id not in self._through:
            self._through[definition.id] = self._find_through(definition)
        return self._through[definition.id]

    def _find_through(self, definition: "Definition") -> Through | None:
        graph = self.graph(definition)
        ports = [net for net in graph.nets.values() if net.kind == "port"]
        inputs = frozenset(graph.key(net.name) for net in ports if net.direction == "input")
        outputs = frozenset(graph.key(net.name) for net in ports if net.direction == "output")
        cell = self.passthrough.get(definition.unit.name)
        if cell is not None:
            if cell.inputs:
                return Through(
                    frozenset(graph.key(name) for name in cell.inputs),
                    frozenset(graph.key(name) for name in cell.outputs),
                )
            return Through(inputs, outputs)
        if len(inputs) != 1 or len(outputs) != 1 or len(ports) != 2:  # noqa: PLR2004
            return None
        (output,) = outputs
        drivers = graph.drivers.get(output, ())
        if all(isinstance(driver, Pin) and driver.child is None for driver in drivers):
            # a wrapper of technology cells, which are not defined
            return Through(inputs, outputs)
        return None

    def _cell(self, inst: Inst, net: Net, driver: bool) -> Iterator[Step]:
        """Across the module of `inst`, if it is a pass-through cell.

        From the output `net` back to the inputs (`driver`), or from the input `net` on to the outputs.
        """
        cell = self.through(inst.definition)
        if cell is None:
            return
        key = self.graph(inst.definition).key(net.name)
        mine, others = (cell.outputs, cell.inputs) if driver else (cell.inputs, cell.outputs)
        if key in mine:
            yield Step("passthrough", tuple((inst, other) for other in sorted(others)), inst=inst)

    # --- trace ---

    def trace(  # noqa: C901, PLR0913
        self,
        src: Node,
        dst: Node,
        through_regs: bool = False,
        control: bool = True,
        src_bits: tuple[int, int] | None = None,
        dst_bits: tuple[int, int] | None = None,
    ) -> list[tuple[Node, Step | None]]:
        """Connection of loads from `src` to `dst`: the nets with the step reaching them. Empty, if there is none.

        The connection with the fewest steps is taken, but data first: a step by a condition counts as many.
        `src_bits` and `dst_bits` (lowest, highest) restrict the start to the loads, which may read one of them,
        and the end to the loads, which may drive one of them.
        `stops` and `ff_stops` tell, where the search stopped.
        """
        target = (dst[0].path, dst[1])
        start = (src[0].path, src[1])
        self.stops = []
        self.ff_stops = 0
        # node -> cost, node in front, the node, step reaching it
        came: dict[tuple[str, str], tuple[int, tuple[str, str] | None, Node, Step | None]] = {
            start: (0, None, src, None)
        }
        queue: list[tuple[int, int, tuple[str, str]]] = [(0, 0, start)]
        count = 0
        done: set[tuple[str, str]] = set()

        def is_target(ident: tuple[str, str]) -> bool:
            return ident == target or (_matches(ident[1], target[1]) and ident[0] == target[0] and self._any(dst))

        while queue and len(came) < _MAX_NODES:
            cost, _, ident = heapq.heappop(queue)
            if ident in done:
                continue
            done.add(ident)
            _, _, node, reached_by = came[ident]
            if is_target(ident):
                hops: list[tuple[Node, Step | None]] = []
                current: tuple[str, str] | None = ident
                while current is not None:
                    _, prev, reached, step = came[current]
                    hops.append((reached, step))
                    current = prev
                return hops[::-1]
            if reached_by is not None and reached_by.kind == "ff" and not through_regs:
                self.ff_stops += 1
                continue
            for step in self.loads(node, src_bits if ident == start else None):
                if step.control and not control:
                    continue
                if step.kind == "unknown" and len(self.stops) < _MAX_STOPS:
                    self.stops.append((node, step))
                step_cost = cost + (_CONTROL_COST if step.control else 1)
                for nxt in step.nets:
                    nxt_ident = (nxt[0].path, nxt[1])
                    if is_target(nxt_ident) and not _overlaps(step.driven, dst_bits):
                        # drives other bits of the target
                        continue
                    if nxt_ident not in came or came[nxt_ident][0] > step_cost:
                        came[nxt_ident] = (step_cost, ident, nxt, step)
                        count += 1
                        heapq.heappush(queue, (step_cost, count, nxt_ident))
        return []

    def _any(self, node: Node) -> bool:
        """`node` stands for multiple nets: reaching any of them is enough."""
        return self.multiple(node)

    # --- data model ---

    def link(self, node: Node, step: Step, driver: bool) -> dm.Link:
        """`step` as [Link][hdl_parser.datamodel.Link]: a driver or load of `node`."""
        fields: dict = {
            "kind": step.kind,
            "nets": tuple(self.path(other) for other in step.nets),
            "conds": tuple(self.path(other) for other in step.conds if other != step.clock),
            "clock": self.path(step.clock) if step.clock else "",
            "control": step.control,
            "multiple": self.multiple(node) or any(self.multiple(other) for other in step.nets),
        }
        record = step.record
        if record is None and step.kind == "passthrough" and step.inst is not None:
            inst = step.inst
            fields["item"] = inst.pin_file.full_id(inst.pin_inst) if inst.pin_file and inst.pin_inst else ""
            fields["file"] = inst.pin_file.file_id if inst.pin_file else ""
            fields["loc"] = inst.pin_inst.loc if inst.pin_inst else None
        elif record is None:
            fields["external"] = True
        elif isinstance(record, Assign):
            process = record.process
            module = step.inst.definition.id if step.inst else ""
            fields["item"] = record.file.full_id(process) if process else module
            # the select of the driven net: the one of the driver, the one of `nets` of a load
            fields["select"] = record.assign.select if step.select is None else step.select
            fields["file"] = record.file.file_id
            fields["loc"] = record.assign.loc
        else:
            fields["item"] = record.file.full_id(record.inst)
            fields["file"] = record.file.file_id
            fields["loc"] = record.con.loc if record.con else record.inst.loc
            if (driver and step.kind not in ("port", "passthrough")) or (not driver and step.kind == "port"):
                net = node[1] if driver else step.nets[0][1] if len(step.nets) == 1 else ""
                written = next((select for key, select in record.writes if _matches(key, net)), "")
                fields["select"] = written if step.select is None else step.select
            if step.kind == "unknown":
                fields["unknown"] = (
                    f"module '{record.inst.module}' is not defined in the project"
                    if record.child is None
                    else f"the port of module '{record.inst.module}' is not known"
                )
        return dm.Link(**fields)

    def hops(self, trace: list[tuple[Node, Step | None]]) -> tuple[dm.Hop, ...]:
        """`trace` as [Hops][hdl_parser.datamodel.Hop]."""
        result = []
        for node, step in trace:
            fields: dict = {"net": self.path(node)}
            if step is not None:
                link = self.link(node, step, driver=False)
                fields.update(kind=link.kind, control=link.control, item=link.item, file=link.file, loc=link.loc)
                fields["select"] = link.select
                record = step.record
                if step.kind == "port" and step.select is None and isinstance(record, Pin):
                    fields["select"] = next((select for key, select in record.writes if _matches(key, node[1])), "")
            result.append(dm.Hop(**fields))
        return tuple(result)

    def stopped(self) -> list[dict[str, Any]]:
        """Where the last trace stopped: the blackboxes it reached."""
        result = []
        seen = set()
        for node, step in self.stops:
            link = self.link(node, step, driver=False)
            if link.item in seen:
                continue
            seen.add(link.item)
            entry: dict[str, Any] = {
                "net": self.path(node),
                "item": link.item,
                "reason": link.unknown,
                "file": link.file,
            }
            if link.loc is not None:
                entry["line"] = link.loc.line
            result.append(entry)
        return result


def _merge(steps: list[Step]) -> Iterator[Step]:
    """`steps` of the iterations of one record: one step per kind and select, with the nets of all of them."""
    kinds: dict[tuple, Step] = {}
    for step in steps:
        ident = (step.kind, step.select, step.bits, step.driven)
        first = kinds.get(ident)
        if first is None:
            kinds[ident] = step
        else:
            kinds[ident] = first._replace(
                nets=tuple(dict.fromkeys((*first.nets, *step.nets))),
                conds=tuple(dict.fromkeys((*first.conds, *step.conds))),
                clock=first.clock or step.clock,
                control=first.control and step.control,
            )
    yield from kinds.values()


def _split_file(path: str) -> tuple[str, str]:
    """File identifier and the rest of the path: `("rtl/top.sv", "top.data[3:0]")`. Selects keep their colons."""
    depth = 0
    cut = -1
    for pos, char in enumerate(path):
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif char == ":" and depth == 0:
            cut = pos
    return (path[:cut], path[cut + 1 :]) if cut >= 0 else ("", path)


def _overlaps(bits: tuple[int, int] | None, other: tuple[int, int] | None) -> bool:
    """The bits may overlap: either is not known (or the whole net), or they share a bit."""
    return bits is None or other is None or (bits[0] <= other[1] and other[0] <= bits[1])


_SV_SELECT = re.compile(r"\[([^\[\]]+)\]")
_SV_PART = re.compile(r"(.+?)([+-]):(.+)", re.DOTALL)
_SV_RANGE = re.compile(r"(.+?)(?<!:):(?!:)(.+)", re.DOTALL)
_VHDL_SELECT = re.compile(r"\((.+?)(?:\s+(to|downto)\s+(.+))?\)", re.DOTALL | re.IGNORECASE)


def _select(scope: Scope | _Bound, select: str, lang: str) -> tuple[int, int, str] | None:  # noqa: PLR0911
    """Bits (lowest, highest) of the select `select` of one dimension, and its text as evaluated: `[7:4]`.

    `None`, if it is not known: an expression which cannot be evaluated, several dimensions, a field, ...
    """
    text = select.strip()

    def value(expr: str) -> int:
        return int(scope.evaluate(expr.strip()).value)  # type: ignore[arg-type]

    try:
        if lang == "vhdl":
            mat = _VHDL_SELECT.fullmatch(text)
            if mat is None:
                return None
            first = value(mat.group(1))
            if mat.group(2) is None:
                return first, first, f"({first})"
            last = value(mat.group(3))
            return min(first, last), max(first, last), f"({first} {mat.group(2).lower()} {last})"
        mat = _SV_SELECT.fullmatch(text)
        if mat is None or "?" in mat.group(1):
            return None
        inner = mat.group(1)
        part = _SV_PART.fullmatch(inner)
        if part is not None:
            base, width = value(part.group(1)), value(part.group(3))
            low, high = (base, base + width - 1) if part.group(2) == "+" else (base - width + 1, base)
            return low, high, f"[{high}:{low}]"
        span = _SV_RANGE.fullmatch(inner)
        if span is not None:
            first, last = value(span.group(1)), value(span.group(2))
            return min(first, last), max(first, last), f"[{first}:{last}]"
        first = value(inner)
    except (Unknown, TypeError, ValueError, ZeroDivisionError):
        return None
    return first, first, f"[{first}]"


def _similar(name: str, names: list[str]) -> tuple[str, ...]:
    import difflib  # noqa: PLC0415

    choices = sorted(set(names))
    found = difflib.get_close_matches(name, choices, n=5, cutoff=0.6)
    lower = name.lower()
    if len(lower) >= 3:  # noqa: PLR2004
        found += [choice for choice in choices if lower in choice.lower() and choice not in found]
    return tuple(found[:5])
