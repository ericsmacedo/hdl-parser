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

"""VHDL Parser.

A recursive-descent parser on top of the token stream of [tokenize][hdl_parser._vhdl.tokenizer.tokenize].

The parser is tolerant by design. It does not try to understand all of VHDL, just the constructs it extracts
information from. Everything else is skipped:

* brackets are always consumed as balanced groups,
* unknown declarations and statements are skipped up to their terminating `;`,
* processes, subprograms and other blocks are skipped up to their `end`,
* nothing is ever skipped beyond the end of an entity or architecture.

An entity becomes a module with its generics as parameters. The instances found in the architectures of an entity
are added to that module.

Supporting a new construct means adding one branch to the related `_parse_*` function. The items of an architecture
are dispatched by their leading keyword: a new one is a function decorated with `_handles`.
"""

import re
from collections.abc import Callable, Iterator
from typing import Literal, NamedTuple, cast

from .. import datamodel as dm  # noqa: TID252
from .._diagnostics import Diagnostics, shorten  # noqa: TID252
from .._tokens import EOF, ID, KW, OPEN, Cursor, SourceMap, Token, Tokens  # noqa: TID252
from .tokenizer import tokenize

_MODES = frozenset(("in", "out", "inout", "buffer", "linkage"))
_OBJECT_CLASSES = frozenset(("constant", "signal", "variable", "file"))
_INSTANCES = frozenset(("entity", "component", "configuration"))
_EDGE_FUNCTIONS = {"rising_edge": "posedge", "falling_edge": "negedge"}
_SUBPROGRAMS = frozenset(("function", "procedure"))
_MAPPED = frozenset(("generic", "port"))
# `end generate` and `end block` close a nesting level
_NESTED = frozenset(("generate", "block"))

_SEMI = frozenset((";",))
_COMMA = frozenset((",",))
_SEMI_OR_DEFAULT = frozenset((";", ":="))
_SEMI_OR_IS = frozenset((";", "is"))
_SEMI_OR_GENERATE = frozenset((";", "generate"))
_SEMI_OR_CHOICE = frozenset((";", "=>"))
_COMMA_OR_ASSOC = frozenset((",", "=>"))
# Type definitions, which contain `;`
_TYPE_BLOCKS = frozenset(("record", "units", "protected"))
_SEMI_OR_TYPE_BLOCK = frozenset((";", *_TYPE_BLOCKS))

_RANGE = re.compile(r"\s*\b(?:downto|to)\b\s*", re.IGNORECASE)


class _Decl(NamedTuple):
    """One Declared Name (Port or Generic)."""

    name: str
    direction: str
    ptype: str
    dtype: str
    dim: str
    default: str
    comment: list[str]
    loc: dm.Location


class _Unit:
    """Entity With The Content Of Its Architectures, Or Package."""

    def __init__(self, name: str, smap: SourceMap, diagnostics: Diagnostics):
        self.name = name
        self.smap = smap
        self.diagnostics = diagnostics
        self.generics: list[_Decl] = []
        self.ports: list[_Decl] = []
        self.constants: list[_Decl] = []
        # signals with the generate and block statements around
        self.signals: list[tuple[_Decl, tuple[dm.Generate, ...]]] = []
        self.typedefs: list[dm.Typedef] = []
        self.functions: list[dm.Function] = []
        self.components: list[dm.Module] = []
        self.processes: list[dm.Process] = []
        self.insts: list[dm.ModuleInstance] = []
        # generate and block statements around the current position
        self.generates: list[dm.Generate] = []
        # label in front of the current item, with the comments in front of it
        self.label: Token | None = None
        self.label_comment: list[str] = []
        # entity, and first architecture
        self.loc: dm.Location | None = None
        self.arch_loc: dm.Location | None = None

    @property
    def label_name(self) -> str:
        """Name of the label in front of the current item."""
        return self.label.text if self.label else ""


def _last(c: Cursor) -> Token:
    """Last consumed token."""
    return c.toks[c.pos - 1] if c.pos else c.toks[0]


# --- generics and ports ---


def _parse_subtype(c: Cursor) -> tuple[str, str]:
    """Parse `type_name [(constraint)]` and return `(dtype, dim)`."""
    if c.peek().kind != ID:
        return "", ""
    start = c.pos
    c.next()
    while c.peek().text == "." and c.peek(1).kind == ID:
        c.next()
        c.next()
    dtype = c.text(start, c.pos).lower()
    dim = ""
    while c.peek().text == "(":
        start = c.pos + 1
        c.skip_balanced()
        dim += f"[{_RANGE.sub(':', c.text(start, c.pos - 1)).strip()}]"
    return dtype, dim


def _parse_interface_decl(c: Cursor, unit: _Unit, report: bool = True) -> list[_Decl]:
    """Parse `[class] name {, name} : [mode] type [(constraint)] [:= default]`.

    `report`: Anything else is reported as skipped item of the entity header.
    """
    comment = c.start_comment()
    start = c.pos
    first = c.peek()
    ptype = ""
    if c.peek().text in _OBJECT_CLASSES and c.peek().kind == KW:
        ptype = c.next().text
    names: list[Token] = []
    while c.peek().kind == ID:
        names.append(c.next())
        if not c.accept(","):
            break
    if not names or not c.accept(":"):
        # nothing we understand, i.e. the type, subprogram and package generics of VHDL-2008
        c.skip_until(_SEMI)
        if report and c.pos > start:
            unit.diagnostics.add(
                "header-item-skipped",
                f"entity '{unit.name}': '{shorten(c.text(start, c.pos))}' in entity header is not understood. "
                "Generics or ports may be missing.",
                unit.smap.span(first, _last(c)),
            )
        return []
    direction = ""
    if c.peek().text in _MODES and c.peek().kind == KW:
        direction = c.next().text
    dtype, dim = _parse_subtype(c)
    default = ""
    c.skip_until(_SEMI_OR_DEFAULT)
    if c.accept(":="):
        start = c.pos
        c.skip_until(_SEMI)
        default = c.text(start, c.pos).strip()
    last = _last(c)
    return [
        _Decl(name.text, direction, ptype, dtype, dim, default, comment, unit.smap.span(first, last, name))
        for name in names
    ]


def _parse_interface_list(c: Cursor, unit: _Unit, report: bool = True) -> list[_Decl]:
    """Parse the parenthesized, semicolon separated declarations of a generic or port clause, or of a subprogram."""
    decls: list[_Decl] = []
    opening = c.next()
    while True:
        tok = c.peek()
        if tok.text == ")":
            c.next()
            break
        if tok.kind == EOF:
            c.unclosed.append(opening)
            break
        if tok.text == ";":
            c.next()
            continue
        pos = c.pos
        decls += _parse_interface_decl(c, unit, report)
        if c.pos == pos:
            # unmatched closing bracket
            c.next()
    c.sink = None
    return decls


def _parse_entity(c: Cursor, unit: _Unit) -> None:
    """Parse `entity name is [generic (...);] [port (...);] ... end`."""
    while True:
        tok = c.peek()
        if tok.kind == EOF:
            return
        if tok.kind == KW:
            if tok.text in ("begin", "end"):
                return
            if tok.text in _MAPPED and c.peek(1).text == "(":
                c.next()
                decls = _parse_interface_list(c, unit)
                if tok.text == "port":
                    unit.ports += decls
                else:
                    unit.generics += decls
                continue
        if tok.text in OPEN:
            c.skip_balanced()
        else:
            c.next()


# --- instances ---


def _is_component_instance(c: Cursor) -> bool:
    """Check for `component_name (generic|port) map` at the current position."""
    toks = c.toks
    idx = c.pos + 1
    while toks[idx].text == "." and toks[idx + 1].kind == ID:
        idx += 2
    return toks[idx].text in _MAPPED and toks[idx].kind == KW and toks[idx + 1].text == "map"


def _parse_map(c: Cursor, smap: SourceMap) -> list[dm.Connection]:
    """Parse the parenthesized associations of a generic or port map."""
    cons: list[tuple[str, str, list[str], dm.Location]] = []
    opening = c.next()
    while True:
        tok = c.peek()
        if tok.text == ")":
            c.next()
            break
        if tok.kind == EOF:
            c.unclosed.append(opening)
            break
        if tok.text == ",":
            c.next()
            continue
        start = c.pos
        first = c.peek()
        comment = c.start_comment()
        c.skip_until(_COMMA_OR_ASSOC)
        port = ""
        if c.peek().text == "=>":
            port = c.text(start, c.pos).strip()
            c.next()
            start = c.pos
            c.skip_until(_COMMA)
        elif c.pos == start:
            # nothing we understand
            c.next()
            continue
        cons.append((port, c.text(start, c.pos).strip(), comment, smap.span(first, _last(c))))
    c.sink = None
    # the comments are complete now
    return [dm.Connection(port=port, con=con, comment=tuple(comment), loc=loc) for port, con, comment, loc in cons]


def _parse_instance(c: Cursor, label: Token, smap: SourceMap) -> dm.ModuleInstance | None:
    """Parse `name [(architecture)] [generic map (...)] [port map (...)];` behind `label : [entity|component]`."""
    if c.peek().kind != ID:
        return None
    # the library and package of the name are not of interest
    module = c.next()
    while c.peek().text == "." and c.peek(1).kind == ID:
        c.next()
        module = c.next()
    if c.peek().text == "(":
        c.skip_balanced()
    maps: dict[str, list[dm.Connection]] = {"generic": [], "port": []}
    while c.peek().text in _MAPPED and c.peek(1).text == "map":
        kind = c.next().text
        c.next()
        if c.peek().text != "(":
            break
        maps[kind] += _parse_map(c, smap)
    return dm.ModuleInstance(
        name=label.text, module=module.text, params=tuple(maps["generic"]), connections=tuple(maps["port"])
    )


def _parse_labeled(c: Cursor, unit: _Unit) -> None:
    """Parse `label : statement`. Any statement but an instance is left to its own handler."""
    comment = list(c.comments.get(c.pos, ()))
    label = c.next()
    c.next()
    tok = c.peek()
    if tok.kind == KW:
        if tok.text not in _INSTANCES:
            unit.label = label
            unit.label_comment = comment
            return
        c.next()
    elif tok.kind != ID or not _is_component_instance(c):
        return
    inst = _parse_instance(c, label, unit.smap)
    c.skip_until(_SEMI)
    c.accept(";")
    if inst:
        update = {"loc": unit.smap.span(label, _last(c), label), "generates": tuple(unit.generates)}
        unit.insts.append(inst.model_copy(update=update))


# --- architecture ---

_Handler = Callable[[Cursor, _Unit], None]
# Parsers of declarations and statements by their leading keyword
_HANDLERS: dict[str, _Handler] = {}


def _handles(*keywords: str) -> Callable[[_Handler], _Handler]:
    """Register the decorated function as parser of the items starting with one of `keywords`."""

    def decorator(func: _Handler) -> _Handler:
        for keyword in keywords:
            if keyword in _HANDLERS:
                raise ValueError(f"Duplicate handler for {keyword!r}")
            _HANDLERS[keyword] = func
        return func

    return decorator


def _skip_statement(c: Cursor) -> None:
    """Skip up to and including the next `;`."""
    c.skip_until(_SEMI)
    c.accept(";")


@_handles("begin", "postponed", "pure", "impure", "generate")
def _handle_prefix(c: Cursor, unit: _Unit) -> None:  # noqa: ARG001
    """Keywords without relevance on their own."""
    c.next()


def _take_comment(c: Cursor, unit: _Unit) -> list[str]:
    """The comments in front of the current item, or in front of its label. They describe the item."""
    return unit.label_comment or list(c.comments.get(c.pos, ()))


def _parse_sensitivity(c: Cursor) -> list[dm.Event]:
    """Parse the optional sensitivity list of a process: `(clk, rst_n)`. `(all)` means everything read."""
    if c.peek().text != "(":
        return []
    events = []
    end = c.match(c.pos) - 1
    c.next()
    while c.pos < end:
        start = c.pos
        c.skip_until(_COMMA)
        signal = c.text(start, c.pos).strip()
        if signal and signal.lower() != "all":
            events.append(dm.Event(signal=signal))
        if c.pos == start or c.peek().text == ",":
            c.next()
    c.skip_to(end + 1)
    return events


def _find_clock(body: list[Token]) -> tuple[str, str]:
    """Clock and its edge within the process `body`: `rising_edge(clk)` or `clk'event and clk = '1'`.

    Both are empty, if there is no clock or more than one.
    """
    clocks: dict[str, tuple[str, str]] = {}
    for idx, tok in enumerate(body[:-3]):
        if tok.kind != ID:
            continue
        edge = _EDGE_FUNCTIONS.get(tok.text.lower())
        if edge and body[idx + 1].text == "(" and body[idx + 2].kind == ID and body[idx + 3].text == ")":
            name = body[idx + 2].text
        elif body[idx + 1].text == "'" and body[idx + 2].text.lower() == "event":
            # the level behind tells the edge: clk'event and clk = '1'
            name = tok.text
            levels = [tok.text for tok in body[idx + 3 : idx + 8] if tok.text in ("'0'", "'1'")]
            if not levels:
                continue
            edge = "posedge" if levels[0] == "'1'" else "negedge"
        else:
            continue
        clocks.setdefault(name.lower(), (name, edge))
    if len(clocks) != 1:
        return "", ""
    return next(iter(clocks.values()))


def _find_reset(body: list[Token], events: list[dm.Event], clock: str) -> tuple[str, str]:
    """Asynchronous reset and its edge: the signal of the sensitivity list, checked by the leading `if`.

    `if rst_n = '0' then ... elsif rising_edge(clk) then`
    """
    begin = next((idx for idx, tok in enumerate(body) if tok.kind == KW and tok.text == "begin"), None)
    if begin is None or not clock or body[begin + 1].text != "if":
        return "", ""
    cond: list[Token] = []
    for tok in body[begin + 2 :]:
        if tok.kind == KW and tok.text == "then":
            break
        cond.append(tok)
    names = {tok.text.lower() for tok in cond if tok.kind == ID}
    if clock.lower() in names or names & {*_EDGE_FUNCTIONS, "event"}:
        # the clock is checked first: a reset within is synchronous
        return "", ""
    for event in events:
        if event.signal.lower() in names:
            low = any(tok.text == "'0'" or (tok.kind == KW and tok.text == "not") for tok in cond)
            return event.signal, "negedge" if low else "posedge"
    return "", ""


@_handles("process")
def _handle_process(c: Cursor, unit: _Unit) -> None:
    """`[label :] process [(sensitivity list)] [is] ... begin ... end process [label];`."""
    comment = _take_comment(c, unit)
    label = unit.label
    first = c.next()
    events = _parse_sensitivity(c)
    start = c.pos
    c.skip_past(frozenset(("process",)))
    body = c.toks[start : c.pos]
    _skip_statement(c)
    clock, clock_edge = _find_clock(body)
    reset, reset_edge = _find_reset(body, events, clock)
    unit.processes.append(
        dm.Process(
            name=label.text if label else "",
            kind="process",
            events=tuple(events),
            clock=clock,
            clock_edge=clock_edge,
            reset=reset,
            reset_edge=reset_edge,
            generates=tuple(unit.generates),
            comment=tuple(comment),
            loc=unit.smap.span(label or first, _last(c)),
        )
    )


def _create_params(decls: list[_Decl]) -> tuple[dm.Param, ...]:
    return tuple(
        dm.Param(
            name=decl.name,
            ptype=decl.ptype,
            dtype=decl.dtype,
            dim=decl.dim,
            default=decl.default,
            comment=tuple(decl.comment),
            loc=decl.loc,
        )
        for decl in decls
    )


def _create_ports(decls: list[_Decl]) -> tuple[dm.Port, ...]:
    return tuple(
        dm.Port(
            name=decl.name,
            direction=decl.direction or "in",
            ptype=decl.ptype,
            dtype=decl.dtype,
            dim=decl.dim,
            default=decl.default,
            comment=tuple(decl.comment),
            loc=decl.loc,
        )
        for decl in decls
    )


@_handles("component")
def _handle_component(c: Cursor, unit: _Unit) -> None:
    """`component name [is] [generic (...);] [port (...);] end component [name];`."""
    first = c.next()
    name = c.peek()
    if name.kind != ID:
        c.skip_past(frozenset(("component",)))
        _skip_statement(c)
        return
    c.next()
    c.accept("is")
    component = _Unit(name.text, unit.smap, unit.diagnostics)
    _parse_entity(c, component)
    _skip_statement(c)
    unit.components.append(
        dm.Module(
            name=name.text,
            params=_create_params(component.generics),
            ports=_create_ports(component.ports),
            loc=unit.smap.span(first, _last(c), name),
        )
    )


@_handles("signal", "constant")
def _handle_object(c: Cursor, unit: _Unit) -> None:
    """`signal|constant name {, name} : type [(constraint)] [:= value];`."""
    is_signal = c.peek().text == "signal"
    decls = _parse_interface_decl(c, unit, report=False)
    _skip_statement(c)
    c.sink = None
    if is_signal:
        generates = tuple(unit.generates)
        unit.signals += [(decl, generates) for decl in decls]
    else:
        unit.constants += decls


def _parse_enum_members(c: Cursor) -> list[tuple[Token, list[str]]]:
    """Parse `(name {, name})`: the literals of an enumeration with their comments."""
    members = []
    opening = c.next()
    while True:
        tok = c.peek()
        if tok.text == ")":
            c.next()
            break
        if tok.kind == EOF:
            c.unclosed.append(opening)
            break
        if tok.text == ",":
            c.next()
            continue
        comment = c.start_comment()
        members.append((c.next(), comment))
    return members


@_handles("type", "subtype")
def _handle_type(c: Cursor, unit: _Unit) -> None:
    """`type name is ...;`, including records, physical and protected types. Likewise subtypes."""
    leading = _take_comment(c, unit)
    comment = c.start_comment()
    comment += leading
    first = c.next()
    name = c.peek()
    if name.kind != ID or c.peek(1).text != "is":
        # incomplete type
        _skip_statement(c)
        c.sink = None
        return
    c.next()
    c.next()
    literals: list[tuple[Token, list[str]]] = []
    fields: list[_Decl] = []
    dtype = ""
    kind: Literal["alias", "enum", "struct"] = "alias"
    if first.text == "type" and c.peek().text == "(":
        kind = "enum"
        literals = _parse_enum_members(c)
    elif c.peek().text == "record":
        kind = "struct"
        c.next()
        while c.peek().kind == ID:
            fields += _parse_interface_decl(c, unit, report=False)
            _skip_statement(c)
    else:
        start = c.pos
        c.skip_until(_SEMI_OR_TYPE_BLOCK)
        block = c.peek().text
        if block in _TYPE_BLOCKS:
            c.skip_past(frozenset((block,)))
        dtype = " ".join(c.text(start, c.pos).split())
    c.sink = comment
    _skip_statement(c)
    c.sink = None
    members = [
        dm.Member(name=tok.text, comment=tuple(member_comment), loc=unit.smap.span(tok, tok))
        for tok, member_comment in literals
    ]
    members += [
        dm.Member(name=decl.name, dtype=decl.dtype, dim=decl.dim, comment=tuple(decl.comment), loc=decl.loc)
        for decl in fields
    ]
    unit.typedefs.append(
        dm.Typedef(
            name=name.text,
            kind=kind,
            dtype=dtype,
            members=tuple(members),
            comment=tuple(comment),
            loc=unit.smap.span(first, _last(c), name),
        )
    )


def _skip_subprogram_body(c: Cursor) -> None:
    """Skip `... begin ... end [function] [name];` behind `is`, including the subprograms within."""
    depth = 1
    while True:
        tok = c.peek()
        if tok.kind == EOF:
            return
        if tok.text in OPEN:
            c.skip_balanced()
            continue
        c.next()
        if tok.kind != KW:
            continue
        if tok.text in _SUBPROGRAMS:
            # declaration or body?
            c.skip_until(_SEMI_OR_IS)
            if c.peek().text == "is" and c.peek(1).text != "new":
                c.next()
                depth += 1
                continue
        elif tok.text == "end":
            nxt = c.peek()
            if nxt.kind == KW and nxt.text not in _SUBPROGRAMS:
                # end of a statement within the subprogram body
                continue
            depth -= 1
        else:
            continue
        _skip_statement(c)
        if depth <= 0:
            return


@_handles(*_SUBPROGRAMS)
def _handle_subprogram(c: Cursor, unit: _Unit) -> None:
    """`function name [(...)] return type [is ... begin ... end [function] [name]];`. Likewise procedures."""
    comment = _take_comment(c, unit)
    first = c.next()
    name = c.peek()
    # the name of an operator is a string: "+"
    named = name.kind in (ID, "str")
    if named:
        c.next()
    args = _parse_interface_list(c, unit, report=False) if c.peek().text == "(" else []
    rtype = dim = ""
    if c.accept("return"):
        rtype, dim = _parse_subtype(c)
    c.skip_until(_SEMI_OR_IS)
    if c.peek().text == "is" and c.peek(1).text != "new":
        c.next()
        _skip_subprogram_body(c)
    else:
        _skip_statement(c)
    if named:
        unit.functions.append(
            dm.Function(
                name=name.text,
                kind=first.text,  # type: ignore[arg-type]
                rtype=rtype,
                dim=dim,
                args=_create_ports(args),
                comment=tuple(comment),
                loc=unit.smap.span(first, _last(c), name),
            )
        )


@_handles("block")
def _handle_block(c: Cursor, unit: _Unit) -> None:
    """`block [(guard)] [is] ... begin ... end block [label];`. The items within are parsed like any other item."""
    c.next()
    if c.peek().text == "(":
        c.skip_balanced()
    c.accept("is")
    unit.generates.append(dm.Generate(kind="block", name=unit.label_name))


@_handles("for", "if", "case")
def _handle_generate(c: Cursor, unit: _Unit) -> None:
    """`for|if|case ... generate ... end generate [label];`. The items within are parsed like any other item."""
    kind = cast("dm.GenerateKind", c.next().text)
    start = c.pos
    c.skip_until(_SEMI_OR_GENERATE)
    if c.peek().text == "generate":
        unit.generates.append(dm.Generate(kind=kind, name=unit.label_name, cond=c.text(start, c.pos).strip()))
        c.next()
    else:
        # configuration specification: for all : comp use entity work.comp;
        c.accept(";")


@_handles("elsif", "else")
def _handle_generate_alternative(c: Cursor, unit: _Unit) -> None:  # noqa: ARG001
    """`elsif ... generate` and `else generate`."""
    c.next()
    c.skip_until(_SEMI_OR_GENERATE)
    if not c.accept("generate"):
        c.accept(";")


@_handles("when")
def _handle_generate_choice(c: Cursor, unit: _Unit) -> None:  # noqa: ARG001
    """`when choice =>` of a case generate."""
    c.next()
    c.skip_until(_SEMI_OR_CHOICE)
    if not c.accept("=>"):
        c.accept(";")


def _parse_end(c: Cursor, unit: _Unit) -> bool:
    """Parse `end ...;` and return whether it is the end of the architecture."""
    c.next()
    nxt = c.peek()
    if nxt.text in _NESTED:
        if unit.generates:
            unit.generates.pop()
    elif not unit.generates and (nxt.kind != KW or nxt.text in ("architecture", "package")):
        return True
    # everything else is the end of something within, i.e. the alternative of a generate
    _skip_statement(c)
    return False


def _parse_architecture(c: Cursor, unit: _Unit) -> bool:
    """Parse declarations and statements up to the `end` of the architecture. Return whether there is an `end`.

    The declarations of a package are parsed likewise.

    Items starting with a keyword are parsed by the related function of `_HANDLERS`.
    """
    handlers = _HANDLERS
    unit.generates = []
    while True:
        tok = c.peek()
        kind = tok.kind
        if kind == KW:
            handler = handlers.get(tok.text)
            if handler:
                handler(c, unit)
            elif tok.text != "end":
                # declaration or statement
                c.next()
                _skip_statement(c)
            elif _parse_end(c, unit):
                return True
        elif kind == ID:
            if c.peek(1).text == ":":
                _parse_labeled(c, unit)
                # the label belongs to the next item
                continue
            # assignment or procedure call
            _skip_statement(c)
        elif kind == EOF:
            return False
        elif tok.text in OPEN:
            c.skip_balanced()
        else:
            c.next()
        unit.label = None
        unit.label_comment = []


# --- design units ---


def _split(tokens: Tokens) -> Iterator[tuple[Token, Tokens]]:
    """Split into entities, architectures and packages. Parsing never continues beyond the end of one of them.

    A package body adds nothing to its package. A package instance (`package p is new ...`) is no package.
    """
    toks = tokens.tokens
    last = len(toks) - 1
    starts = [
        idx
        for idx in range(last - 2)
        if toks[idx].kind == KW
        and toks[idx + 1].kind == ID
        and (
            (toks[idx].text == "entity" and toks[idx + 2].text == "is")
            or (toks[idx].text == "architecture" and toks[idx + 2].text == "of")
            or (toks[idx].text == "package" and toks[idx + 2].text == "is" and toks[idx + 3].text != "new")
        )
    ]
    for start, end in zip(starts, [*starts[1:], last], strict=False):
        eof = Token(EOF, "", toks[end].start, toks[end].start, ())
        comments = {idx - start: tokens.comments[idx] for idx in range(start, end + 1) if idx in tokens.comments}
        trailing = {idx - start: tokens.trailing[idx] for idx in range(start, end) if idx in tokens.trailing}
        yield toks[start], Tokens(tokens.source, [*toks[start:end], eof], comments, trailing, tokens.gaps)


def _skip_end(c: Cursor) -> bool:
    """Consume everything up to and including `end ...;`. Return whether there is an `end`."""
    while True:
        tok = c.peek()
        if tok.kind == EOF or (tok.kind == KW and tok.text == "end"):
            break
        if tok.text in OPEN:
            c.skip_balanced()
        else:
            c.next()
    ended = c.peek().kind != EOF
    c.skip_until(_SEMI)
    c.accept(";")
    return ended


def _parse_units(tokens: Tokens, diagnostics: Diagnostics) -> tuple[list[_Unit], list[_Unit]]:
    """Parse all entities with their architectures, and all packages."""
    smap = SourceMap(tokens.source)
    units: dict[str, _Unit] = {}
    packages: list[_Unit] = []
    for tok, unit_tokens in _split(tokens):
        c = Cursor(unit_tokens)
        c.next()
        name_tok = c.next()
        if tok.text == "architecture":
            c.next()
            name_tok = c.next()
        name = name_tok.text
        c.accept("is")
        if tok.text == "package":
            unit = _Unit(name, smap, diagnostics)
            packages.append(unit)
            ended = _parse_architecture(c, unit)
            _skip_statement(c)
            unit.loc = smap.span(tok, _last(c), name_tok)
        else:
            # identifiers are case insensitive
            unit = units.setdefault(name.lower(), _Unit(name, smap, diagnostics))
            if tok.text == "entity":
                _parse_entity(c, unit)
                ended = _skip_end(c)
                if unit.loc is None:
                    unit.loc = smap.span(tok, _last(c), name_tok)
            else:
                ended = _parse_architecture(c, unit)
                _skip_statement(c)
                if unit.arch_loc is None:
                    unit.arch_loc = smap.span(tok, _last(c), name_tok)
        if not ended:
            diagnostics.add("missing-end", f"{tok.text} '{name}' has no 'end'.", smap.span(tok, name_tok))
        for opening in c.unclosed:
            diagnostics.add("unbalanced-bracket", f"'{opening.text}' is never closed.", smap.span(opening, opening))
    return list(units.values()), packages


# --- data model ---


def _create_signals(unit: _Unit) -> tuple[dm.Signal, ...]:
    return tuple(
        dm.Signal(
            name=decl.name,
            dtype=decl.dtype,
            dim=decl.dim,
            default=decl.default,
            generates=generates,
            comment=tuple(decl.comment),
            loc=decl.loc,
        )
        for decl, generates in unit.signals
    )


def parse(text: str, diagnostics: Diagnostics | None = None) -> dm.File:
    """Parse VHDL `text` and return its entities as modules, and its packages.

    The constants of architectures and packages are local parameters.
    Problems are reported to `diagnostics`. The result has neither path, nor identifiers, nor diagnostics.
    """
    units, packages = _parse_units(tokenize(text), diagnostics or Diagnostics("<text>"))
    return dm.File(
        path=None,
        modules=tuple(
            dm.Module(
                name=unit.name,
                params=_create_params(unit.generics),
                localparams=_create_params(unit.constants),
                ports=_create_ports(unit.ports),
                signals=_create_signals(unit),
                typedefs=tuple(unit.typedefs),
                functions=tuple(unit.functions),
                processes=tuple(unit.processes),
                components=tuple(unit.components),
                insts=tuple(unit.insts),
                partial=unit.loc is None,
                loc=unit.loc or unit.arch_loc,
            )
            for unit in units
        ),
        packages=tuple(
            dm.Package(
                name=unit.name,
                localparams=_create_params(unit.constants),
                typedefs=tuple(unit.typedefs),
                functions=tuple(unit.functions),
                components=tuple(unit.components),
                loc=unit.loc,
            )
            for unit in packages
        ),
    )
