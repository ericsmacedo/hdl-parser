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
from typing import NamedTuple

from .. import datamodel as dm  # noqa: TID252
from .._tokens import EOF, ID, KW, OPEN, Cursor, Token, Tokens  # noqa: TID252
from .tokenizer import tokenize

_MODES = frozenset(("in", "out", "inout", "buffer", "linkage"))
_OBJECT_CLASSES = frozenset(("constant", "signal", "variable", "file"))
_INSTANCES = frozenset(("entity", "component", "configuration"))
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


class _Unit:
    """Entity With The Instances Of Its Architectures."""

    __slots__ = ("depth", "generics", "insts", "name", "ports")

    def __init__(self, name: str):
        self.name = name
        self.generics: list[_Decl] = []
        self.ports: list[_Decl] = []
        self.insts: list[dm.ModuleInstance] = []
        # nesting level of generate and block statements
        self.depth = 0


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


def _parse_interface_decl(c: Cursor) -> list[_Decl]:
    """Parse `[class] name {, name} : [mode] type [(constraint)] [:= default]`."""
    comment = c.start_comment()
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
    return [_Decl(name.text, direction, ptype, dtype, dim, default, comment) for name in names]


def _parse_interface_list(c: Cursor) -> list[_Decl]:
    """Parse the parenthesized, semicolon separated declarations of a generic or port clause."""
    decls: list[_Decl] = []
    c.next()
    while True:
        tok = c.peek()
        if tok.text == ")":
            c.next()
            break
        if tok.kind == EOF:
            break
        if tok.text == ";":
            c.next()
            continue
        pos = c.pos
        decls += _parse_interface_decl(c)
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
                decls = _parse_interface_list(c)
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


def _parse_port_map(c: Cursor) -> list[dm.Connection]:
    """Parse the parenthesized connections of an instance."""
    cons: list[tuple[str, str, list[str]]] = []
    c.next()
    while True:
        tok = c.peek()
        if tok.text == ")":
            c.next()
            break
        if tok.kind == EOF:
            break
        if tok.text == ",":
            c.next()
            continue
        start = c.pos
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
        cons.append((port, c.text(start, c.pos).strip(), comment))
    c.sink = None
    # the comments are complete now
    return [dm.Connection(port=port, con=con, comment=tuple(comment)) for port, con, comment in cons]


def _parse_instance(c: Cursor, label: Token) -> dm.ModuleInstance | None:
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
    cons: list[dm.Connection] = []
    while c.peek().text in _MAPPED and c.peek(1).text == "map":
        is_port = c.next().text == "port"
        c.next()
        if c.peek().text != "(":
            break
        if is_port:
            cons += _parse_port_map(c)
        else:
            c.skip_balanced()
    return dm.ModuleInstance(name=label.text, module=module.text, connections=tuple(cons))


def _parse_labeled(c: Cursor, unit: _Unit) -> None:
    """Parse `label : statement`. Any statement but an instance is left to its own handler."""
    label = c.next()
    c.next()
    tok = c.peek()
    if tok.kind == KW:
        if tok.text not in _INSTANCES:
            return
        c.next()
    elif tok.kind != ID or not _is_component_instance(c):
        return
    inst = _parse_instance(c, label)
    if inst:
        unit.insts.append(inst)
    c.skip_until(_SEMI)
    c.accept(";")


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


@_handles("process")
def _handle_process(c: Cursor, unit: _Unit) -> None:  # noqa: ARG001
    """`process ... end process [label];`."""
    c.skip_past(frozenset(("process",)))
    _skip_statement(c)


@_handles("component")
def _handle_component(c: Cursor, unit: _Unit) -> None:  # noqa: ARG001
    """`component name ... end component [name];`."""
    c.skip_past(frozenset(("component",)))
    _skip_statement(c)


@_handles("type")
def _handle_type(c: Cursor, unit: _Unit) -> None:  # noqa: ARG001
    """`type name is ...;`, including records, physical and protected types."""
    c.next()
    c.skip_until(_SEMI_OR_TYPE_BLOCK)
    block = c.peek().text
    if block in _TYPE_BLOCKS:
        c.skip_past(frozenset((block,)))
    _skip_statement(c)


@_handles(*_SUBPROGRAMS)
def _handle_subprogram(c: Cursor, unit: _Unit) -> None:  # noqa: ARG001
    """`function name (...) return type [is ... begin ... end [function] [name]];`. Likewise procedures."""
    depth = 0
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


@_handles("block")
def _handle_block(c: Cursor, unit: _Unit) -> None:
    """`block [(guard)] [is] ... begin ... end block [label];`. The items within are parsed like any other item."""
    c.next()
    if c.peek().text == "(":
        c.skip_balanced()
    c.accept("is")
    unit.depth += 1


@_handles("for", "if", "case")
def _handle_generate(c: Cursor, unit: _Unit) -> None:
    """`for|if|case ... generate ... end generate [label];`. The items within are parsed like any other item."""
    c.next()
    c.skip_until(_SEMI_OR_GENERATE)
    if c.accept("generate"):
        unit.depth += 1
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
        unit.depth = max(unit.depth - 1, 0)
    elif not unit.depth and (nxt.kind != KW or nxt.text == "architecture"):
        return True
    # everything else is the end of something within, i.e. the alternative of a generate
    _skip_statement(c)
    return False


def _parse_architecture(c: Cursor, unit: _Unit) -> None:
    """Parse declarations and statements up to the `end` of the architecture.

    Items starting with a keyword are parsed by the related function of `_HANDLERS`.
    """
    handlers = _HANDLERS
    unit.depth = 0
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
                return
        elif kind == ID:
            if c.peek(1).text == ":":
                _parse_labeled(c, unit)
            else:
                # assignment or procedure call
                _skip_statement(c)
        elif kind == EOF:
            return
        elif tok.text in OPEN:
            c.skip_balanced()
        else:
            c.next()


# --- design units ---


def _split(tokens: Tokens) -> Iterator[tuple[Token, Tokens]]:
    """Split into entities and architectures. Parsing never continues beyond the end of one of them."""
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
        )
    ]
    for start, end in zip(starts, [*starts[1:], last], strict=False):
        eof = Token(EOF, "", toks[end].start, toks[end].start, ())
        comments = {idx - start: tokens.comments[idx] for idx in range(start, end + 1) if idx in tokens.comments}
        yield toks[start], Tokens(tokens.source, [*toks[start:end], eof], comments, tokens.gaps)


def _parse_units(tokens: Tokens) -> list[_Unit]:
    """Parse all entities and architectures."""
    units: dict[str, _Unit] = {}
    for tok, unit_tokens in _split(tokens):
        c = Cursor(unit_tokens)
        c.next()
        name = c.next().text
        if tok.text == "architecture":
            c.next()
            name = c.next().text
        # identifiers are case insensitive
        key = name.lower()
        unit = units.get(key)
        if unit is None:
            unit = units[key] = _Unit(name)
        c.accept("is")
        if tok.text == "entity":
            _parse_entity(c, unit)
        else:
            _parse_architecture(c, unit)
    return list(units.values())


# --- data model ---


def parse(text: str) -> tuple[dm.Module, ...]:
    """Parse VHDL `text` and return its entities as modules."""
    return tuple(
        dm.Module(
            name=unit.name,
            params=tuple(
                dm.Param(
                    name=decl.name,
                    ptype=decl.ptype,
                    dim=decl.dim,
                    default=decl.default,
                    comment=tuple(decl.comment),
                )
                for decl in unit.generics
            ),
            ports=tuple(
                dm.Port(
                    name=decl.name,
                    direction=decl.direction or "in",
                    ptype=decl.ptype,
                    dtype=decl.dtype,
                    dim=decl.dim,
                    comment=tuple(decl.comment),
                )
                for decl in unit.ports
            ),
            insts=tuple(unit.insts),
        )
        for unit in _parse_units(tokenize(text))
    )
