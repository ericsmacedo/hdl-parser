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
`top.u_core.u_alu.result_o`. Labels of generate blocks are part of the path (`top.g_a.u_sub.x`). Instance arrays
and `for` generate constructs are not unrolled: an index of the path is ignored, and the entries are marked by
`multiple`.

The granularity is the whole signal. The select of an assignment (`a[3:0]`) is kept as text.
"""

import heapq
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, NamedTuple

from . import _refs
from . import datamodel as dm
from ._elab import Elaboration, Scope

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
_FORMAL = re.compile(r"\s*([\w$]+)")
_IDENTIFIER = re.compile(r"[a-zA-Z_][\w$]*")
_MAX_NODES = 200_000
# A step by a condition counts as this many steps by data
_CONTROL_COST = 1000


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
    """

    name: str
    kind: str
    direction: str = ""
    file: dm.File | None = None
    item: dm.Port | dm.Signal | None = None


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


Driver = Assign | Pin


class Graph:
    """Net Graph Of One Module: Nets, With Their Drivers And Loads.

    VHDL names are not case sensitive: the keys of the nets of a VHDL module are lower case.
    """

    def __init__(self, project: "Project", definition: "Definition"):
        self.definition = definition
        self.lang = definition.file.lang
        self.nets: dict[str, Net] = {}
        self.drivers: dict[str, list[Driver]] = {}
        self.loads: dict[str, list[Driver]] = {}
        # instances by the key of their hierarchical name, and their pins
        self.insts: dict[str, tuple[dm.File, dm.ModuleInstance]] = {}
        self.pins: dict[int, list[Pin]] = {}
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
        """Key of the net `name`, as it is used within the generate blocks `generates`. `None`, if there is none."""
        labels = [generate.name for generate in generates if generate.name]
        for number in range(len(labels), -1, -1):
            key = self.key(".".join((*labels[:number], name)))
            if key in self.nets:
                return key
        return None

    # --- creation ---

    def _add_nets(self, file: dm.File, unit: dm.Module | dm.Package) -> None:
        for port in getattr(unit, "ports", ()):
            direction = _DIRECTIONS.get(port.direction, "")
            self.nets.setdefault(self.key(port.name), Net(port.name, "port", direction, file, port))
        for signal in getattr(unit, "signals", ()):
            name = ".".join((*(generate.name for generate in signal.generates if generate.name), signal.name))
            self.nets.setdefault(self.key(name), Net(name, "signal", "", file, signal))
        for inst in getattr(unit, "insts", ()):
            name = ".".join((*(generate.name for generate in inst.generates if generate.name), inst.name))
            self.insts.setdefault(self.key(name), (file, inst))

    def _add_assigns(self, file: dm.File, unit: dm.Module | dm.Package) -> None:
        for assign in getattr(unit, "assigns", ()):
            self._add_assign(file, assign, None, "assign", "")
        for process in getattr(unit, "processes", ()):
            kind = _process_kind(process)
            prefix = file.full_id(process).rpartition(":")[2].partition(".")[2]
            # variables: assigned within the process, but no nets of the module
            variables: dict[str, str] = {}
            for assign in process.assigns:
                if self.resolve(assign.target, process.generates) is None:
                    name = f"{prefix}.{assign.target}"
                    key = self.key(name)
                    self.nets.setdefault(key, Net(name, "variable", "", file))
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
            self.nets.setdefault(dst, Net(assign.target, "implicit", "", file))
        reads = _refs.unique(key for key in map(resolve, assign.reads) if key)
        conds = _refs.unique(key for key in (*map(resolve, assign.conds), clock) if key and key not in reads)
        record = Assign(dst, reads, conds, kind, clock, file, assign, process)
        self.drivers.setdefault(dst, []).append(record)
        for key in (*reads, *conds):
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
            if con.port:
                mat = _FORMAL.match(con.port)
                formal = mat.group(1) if mat else con.port
                port = by_name.get(formal.lower() if casefold else formal)
            else:
                port = ports[position] if position < len(ports) else None
                position += 1
            if port is not None:
                connected.add(port.name)
            pins.append(self._pin(name, file, inst, child, port, con.con, con))
        if inst.wildcard:
            pins += [
                self._pin(name, file, inst, child, port, port.name, None)
                for port in ports
                if port.name not in connected and self.resolve(port.name, inst.generates)
            ]
        self.pins[id(inst)] = pins
        for pin in pins:
            for key, _ in pin.writes:
                self.drivers.setdefault(key, []).append(pin)
            for key in pin.reads:
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
    ) -> Pin:
        direction = _DIRECTIONS.get(port.direction, "unknown") if port and child else "unknown"
        lang = file.lang
        if lang == "sv" and _IDENTIFIER.fullmatch(expr) and self.resolve(expr, inst.generates) is None:
            # Verilog: a net connected to an instance is declared implicitly
            self.nets.setdefault(self.key(expr), Net(expr, "implicit", "", file))
        reads: tuple[str, ...] = ()
        writes: tuple[tuple[str, str], ...] = ()
        if expr and expr.lower() != "open":
            if direction in ("input", "inout", "unknown"):
                keys = (self.resolve(name, inst.generates) for name in _refs.reads_text(expr, lang))
                reads = _refs.unique(key for key in keys if key)
            if direction in ("output", "inout", "unknown"):
                targets = _refs.targets_text(expr, lang)
                found = ((self.resolve(target.name, inst.generates), target.select) for target in targets)
                writes = tuple((key, select) for key, select in found if key)
        return Pin(name, file, inst, child, port.name if port else "", direction, reads, writes, con)


def _process_kind(process: dm.Process) -> str:
    """`ff`, `latch` or `comb`."""
    if process.kind == "always_ff" or process.clock or any(event.edge for event in process.events):
        return "ff"
    if process.kind == "always_latch":
        return "latch"
    return "comb"


# --- hierarchy ---


class Inst:
    """One Instance Within The Hierarchy Below A Top.

    Attributes:
        path: Instance path: `top`, `top.u_core`, `top.g_a.u_sub`.
        definition: Its module.
        scope: Values of its parameters.
        parent: Instance it is located in. `None` for the top.
        pin_file: File of the instance within `parent`.
        pin_inst: The instance within `parent`.
        multiple: It, or an instance above, is created multiple times (array or `for` generate).
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
    ):
        self.path = path
        self.definition = definition
        self.scope = scope
        self.parent = parent
        self.pin_file = pin_file
        self.pin_inst = pin_inst
        self.multiple = multiple
        self.children: dict[int, Inst | None] = {}
        self.active: dict[str, bool | None] = {}


Node = tuple[Inst, str]
"""A Net Within An Instance: The Instance And The Key Of The Net."""


class Step(NamedTuple):
    """One Driver Or Load Of A Net.

    Attributes:
        kind: `assign`, `comb`, `ff`, `latch`, `inst` (a pin of an instance), `port` (across a port of the module)
              or `unknown` (a pin of a module, which is not defined).
        nets: The nets on the other side: the ones read by a driver, the ones driven by a load.
        conds: Driver: the nets read by its conditions.
        control: Load: the net is read by a condition (or as clock) only.
        clock: The clock of a flip-flop.
        record: The assignment or pin. `None` for a port of the top.
        inst: The instance the record is located in.
    """

    kind: str
    nets: tuple[Node, ...] = ()
    conds: tuple[Node, ...] = ()
    control: bool = False
    clock: Node | None = None
    record: Driver | None = None
    inst: Inst | None = None


class Connectivity:
    """Drivers And Loads Of The Nets Of A Project, With The Parameter Values Of One Top."""

    def __init__(self, project: "Project", params: dict[str, dm.Value] | None = None):
        self.project = project
        self.elab = Elaboration(project)
        self.params = params or {}
        self.tops: dict[str, Inst] = {}

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

    def child(self, parent: Inst, file: dm.File, inst: dm.ModuleInstance) -> Inst | None:
        """Instance `inst` within `parent`. `None`, if its module is not defined, or contains itself."""
        if id(inst) in parent.children:
            return parent.children[id(inst)]
        definition = self.project._resolve_inst(file, inst)
        child = None
        ancestors = []
        node: Inst | None = parent
        while node is not None:
            ancestors.append(node.definition.id)
            node = node.parent
        if definition is not None and definition.id not in ancestors:
            scope = self.elab.scope(definition, self.elab.overrides(parent.scope, inst, file.lang, definition))
            self.elab.parents[id(scope)] = parent.scope
            name = ".".join((*(generate.name for generate in inst.generates if generate.name), inst.name))
            multiple = parent.multiple or bool(inst.dim) or any(generate.kind == "for" for generate in inst.generates)
            child = Inst(f"{parent.path}.{name}", definition, scope, parent, file, inst, multiple)
        parent.children[id(inst)] = child
        return child

    def active(self, inst: Inst, generates: tuple[dm.Generate, ...]) -> bool:
        """Whether the generate constructs `generates` are created within `inst`. Unknown conditions are."""
        for generate in generates:
            if generate.kind == "if" and generate.cond and self._value(inst, generate.cond) is False:
                return False
            if any(self._value(inst, other) is True for other in generate.others):
                # an alternative in front is created instead
                return False
        return True

    @staticmethod
    def _value(inst: Inst, cond: str) -> bool | None:
        """Value of the condition `cond` within `inst`. `None`, if it is not known."""
        if cond not in inst.active:
            value = inst.scope.value_of(cond).value
            inst.active[cond] = None if value is None else bool(value)
        return inst.active[cond]

    def locate(self, path: str) -> Node:
        """The net with the instance path `path`: `top.u_core.result_o`. Raises `PathError`."""
        if ":" in path:
            file_id, _, local = path.rpartition(":")
            top_name, *rest = local.split(".")
            top_name = f"{file_id}:{top_name}"
        else:
            top_name, *rest = path.split(".")
        rest = [_INDEX.sub("", step).strip() for step in rest]
        inst = self.top(top_name)
        if inst is None:
            raise PathError(f"'{top_name}' is no module of the project.", self._similar_units(top_name))
        if not rest:
            raise PathError(f"'{path}' names a module, but no signal.")
        index = 0
        while True:
            graph = self.graph(inst.definition)
            for end in range(len(rest) - 1, index, -1):
                found = graph.insts.get(graph.key(".".join(rest[index:end])))
                if found is not None:
                    child = self.child(inst, *found)
                    if child is None:
                        module = found[1].module
                        raise PathError(f"module '{module}' of '{inst.path}.{'.'.join(rest[index:end])}' is not known.")
                    inst = child
                    index = end
                    break
            else:
                name = ".".join(rest[index:])
                key = graph.key(name)
                if key not in graph.nets:
                    names = [net.name for net in graph.nets.values()]
                    names += [found[1].name for found in graph.insts.values()]
                    raise PathError(f"'{inst.path}' has no signal '{name}'.", _similar(name, names))
                return inst, key

    def _similar_units(self, name: str) -> tuple[str, ...]:
        names = [definition.unit.name for definition in self.project._all_modules]
        return _similar(name.rpartition(":")[2], names)

    # --- drivers and loads ---

    def net(self, node: Node) -> Net:
        inst, key = node
        return self.graph(inst.definition).nets[key]

    def path(self, node: Node) -> str:
        return f"{node[0].path}.{self.net(node).name}"

    def drivers(self, node: Node) -> Iterator[Step]:
        """Drivers of the net `node`."""
        inst, key = node
        graph = self.graph(inst.definition)
        for record in graph.drivers.get(key, ()):
            if isinstance(record, Assign):
                if self.active(inst, record.generates):
                    nets = tuple((inst, read) for read in record.reads)
                    conds = tuple((inst, cond) for cond in record.conds)
                    clock = (inst, record.clock) if record.clock else None
                    yield Step(record.kind, nets, conds, clock=clock, record=record, inst=inst)
            elif self.active(inst, record.inst.generates):
                child = self.child(inst, record.file, record.inst)
                if child is None or not record.port:
                    yield Step("unknown", record=record, inst=inst)
                else:
                    port = self.graph(child.definition).key(record.port)
                    yield Step("inst", ((child, port),), record=record, inst=inst)
        net = graph.nets[key]
        if net.kind == "port" and net.direction in ("input", "inout"):
            yield from self._across(inst, net, reads=True)

    def loads(self, node: Node) -> Iterator[Step]:
        """Loads of the net `node`."""
        inst, key = node
        graph = self.graph(inst.definition)
        for record in graph.loads.get(key, ()):
            if isinstance(record, Assign):
                if self.active(inst, record.generates):
                    control = key not in record.reads
                    yield Step(record.kind, ((inst, record.dst),), control=control, record=record, inst=inst)
            elif self.active(inst, record.inst.generates):
                child = self.child(inst, record.file, record.inst)
                if child is None or not record.port:
                    yield Step("unknown", record=record, inst=inst)
                else:
                    port = self.graph(child.definition).key(record.port)
                    yield Step("inst", ((child, port),), record=record, inst=inst)
        net = graph.nets[key]
        if net.kind == "port" and net.direction in ("output", "inout"):
            yield from self._across(inst, net, reads=False)

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
                yield Step("port", tuple((parent, other) for other in nets), record=pin, inst=parent)

    # --- trace ---

    def trace(
        self, src: Node, dst: Node, through_regs: bool = False, control: bool = True
    ) -> list[tuple[Node, Step | None]]:
        """Connection of loads from `src` to `dst`: the nets with the step reaching them. Empty, if there is none.

        The connection with the fewest steps is taken, but data first: a step by a condition counts as many.
        """
        target = (dst[0].path, dst[1])
        start = (src[0].path, src[1])
        # node -> cost, node in front, the node, step reaching it
        came: dict[tuple[str, str], tuple[int, tuple[str, str] | None, Node, Step | None]] = {
            start: (0, None, src, None)
        }
        queue: list[tuple[int, int, tuple[str, str]]] = [(0, 0, start)]
        count = 0
        done: set[tuple[str, str]] = set()
        while queue and len(came) < _MAX_NODES:
            cost, _, ident = heapq.heappop(queue)
            if ident in done:
                continue
            done.add(ident)
            _, _, node, reached_by = came[ident]
            if ident == target:
                hops: list[tuple[Node, Step | None]] = []
                current: tuple[str, str] | None = ident
                while current is not None:
                    _, prev, reached, step = came[current]
                    hops.append((reached, step))
                    current = prev
                return hops[::-1]
            if reached_by is not None and reached_by.kind == "ff" and not through_regs:
                continue
            for step in self.loads(node):
                if step.control and not control:
                    continue
                step_cost = cost + (_CONTROL_COST if step.control else 1)
                for nxt in step.nets:
                    nxt_ident = (nxt[0].path, nxt[1])
                    if nxt_ident not in came or came[nxt_ident][0] > step_cost:
                        came[nxt_ident] = (step_cost, ident, nxt, step)
                        count += 1
                        heapq.heappush(queue, (step_cost, count, nxt_ident))
        return []

    # --- data model ---

    def link(self, node: Node, step: Step, driver: bool) -> dm.Link:
        """`step` as [Link][hdl_parser.datamodel.Link]: a driver or load of `node`."""
        fields: dict = {
            "kind": step.kind,
            "nets": tuple(self.path(other) for other in step.nets),
            "conds": tuple(self.path(other) for other in step.conds if other != step.clock),
            "clock": self.path(step.clock) if step.clock else "",
            "control": step.control,
            "multiple": node[0].multiple or any(other[0].multiple for other in step.nets),
        }
        record = step.record
        if record is None:
            fields["external"] = True
        elif isinstance(record, Assign):
            process = record.process
            module = step.inst.definition.id if step.inst else ""
            fields["item"] = record.file.full_id(process) if process else module
            fields["select"] = record.assign.select if driver else ""
            fields["file"] = record.file.file_id
            fields["loc"] = record.assign.loc
        else:
            fields["item"] = record.file.full_id(record.inst)
            fields["file"] = record.file.file_id
            fields["loc"] = record.con.loc if record.con else record.inst.loc
            if driver and step.kind != "port":
                fields["select"] = next((select for key, select in record.writes if key == node[1]), "")
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
                record = step.record
                if isinstance(record, Assign):
                    fields["select"] = record.assign.select
                elif record is not None and step.kind == "port":
                    fields["select"] = next((select for key, select in record.writes if key == node[1]), "")
            result.append(dm.Hop(**fields))
        return tuple(result)


def _similar(name: str, names: list[str]) -> tuple[str, ...]:
    import difflib  # noqa: PLC0415

    choices = sorted(set(names))
    found = difflib.get_close_matches(name, choices, n=5, cutoff=0.6)
    lower = name.lower()
    if len(lower) >= 3:  # noqa: PLR2004
        found += [choice for choice in choices if lower in choice.lower() and choice not in found]
    return tuple(found[:5])
