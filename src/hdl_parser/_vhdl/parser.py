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
from typing import NamedTuple, cast

from .. import datamodel as dm  # noqa: TID252
from .._diagnostics import Diagnostics, shorten  # noqa: TID252
from .._tokens import EOF, ID, KW, OPEN, Cursor, SourceMap, Token, Tokens  # noqa: TID252
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
    loc: dm.Location


class _Unit:
    """Entity With The Instances Of Its Architectures."""

    __slots__ = (
        "arch_loc",
        "diagnostics",
        "generates",
        "generics",
        "insts",
        "label",
        "loc",
        "name",
        "ports",
        "smap",
    )

    def __init__(self, name: str, smap: SourceMap, diagnostics: Diagnostics):
        self.name = name
        self.smap = smap
        self.diagnostics = diagnostics
        self.generics: list[_Decl] = []
        self.ports: list[_Decl] = []
        self.insts: list[dm.ModuleInstance] = []
        # generate and block statements around the current position, and the label parsed last
        self.generates: list[dm.Generate] = []
        self.label = ""
        # entity, and first architecture
        self.loc: dm.Location | None = None
        self.arch_loc: dm.Location | None = None


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


def _parse_interface_decl(c: Cursor, unit: _Unit) -> list[_Decl]:
    """Parse `[class] name {, name} : [mode] type [(constraint)] [:= default]`."""
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
        if c.pos > start:
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


def _parse_interface_list(c: Cursor, unit: _Unit) -> list[_Decl]:
    """Parse the parenthesized, semicolon separated declarations of a generic or port clause."""
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
        decls += _parse_interface_decl(c, unit)
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
    label = c.next()
    c.next()
    tok = c.peek()
    if tok.kind == KW:
        if tok.text not in _INSTANCES:
            unit.label = label.text
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
    unit.generates.append(dm.Generate(kind="block", name=unit.label))


@_handles("for", "if", "case")
def _handle_generate(c: Cursor, unit: _Unit) -> None:
    """`for|if|case ... generate ... end generate [label];`. The items within are parsed like any other item."""
    kind = cast("dm.GenerateKind", c.next().text)
    start = c.pos
    c.skip_until(_SEMI_OR_GENERATE)
    if c.peek().text == "generate":
        unit.generates.append(dm.Generate(kind=kind, name=unit.label, cond=c.text(start, c.pos).strip()))
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
    elif not unit.generates and (nxt.kind != KW or nxt.text == "architecture"):
        return True
    # everything else is the end of something within, i.e. the alternative of a generate
    _skip_statement(c)
    return False


def _parse_architecture(c: Cursor, unit: _Unit) -> bool:
    """Parse declarations and statements up to the `end` of the architecture. Return whether there is an `end`.

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
            else:
                # assignment or procedure call
                _skip_statement(c)
        elif kind == EOF:
            return False
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


def _parse_units(tokens: Tokens, diagnostics: Diagnostics) -> list[_Unit]:
    """Parse all entities and architectures."""
    smap = SourceMap(tokens.source)
    units: dict[str, _Unit] = {}
    for tok, unit_tokens in _split(tokens):
        c = Cursor(unit_tokens)
        c.next()
        name_tok = c.next()
        if tok.text == "architecture":
            c.next()
            name_tok = c.next()
        name = name_tok.text
        # identifiers are case insensitive
        key = name.lower()
        unit = units.get(key)
        if unit is None:
            unit = units[key] = _Unit(name, smap, diagnostics)
        c.accept("is")
        if tok.text == "entity":
            _parse_entity(c, unit)
            ended = _skip_end(c)
            if unit.loc is None:
                unit.loc = smap.span(tok, _last(c), name_tok)
        else:
            ended = _parse_architecture(c, unit)
            c.skip_until(_SEMI)
            c.accept(";")
            if unit.arch_loc is None:
                unit.arch_loc = smap.span(tok, _last(c), name_tok)
        if not ended:
            diagnostics.add("missing-end", f"{tok.text} '{name}' has no 'end'.", smap.span(tok, name_tok))
        for opening in c.unclosed:
            diagnostics.add("unbalanced-bracket", f"'{opening.text}' is never closed.", smap.span(opening, opening))
    return list(units.values())


# --- data model ---


def parse(text: str, diagnostics: Diagnostics | None = None) -> dm.File:
    """Parse VHDL `text` and return its entities as modules. Problems are reported to `diagnostics`.

    The result has neither path, nor identifiers, nor diagnostics.
    """
    units = _parse_units(tokenize(text), diagnostics or Diagnostics("<text>"))
    modules = tuple(
        dm.Module(
            name=unit.name,
            params=tuple(
                dm.Param(
                    name=decl.name,
                    ptype=decl.ptype,
                    dim=decl.dim,
                    default=decl.default,
                    comment=tuple(decl.comment),
                    loc=decl.loc,
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
                    loc=decl.loc,
                )
                for decl in unit.ports
            ),
            insts=tuple(unit.insts),
            loc=unit.loc or unit.arch_loc,
        )
        for unit in units
    )
    return dm.File(path=None, modules=modules)
