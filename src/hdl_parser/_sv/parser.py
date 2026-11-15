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

"""SystemVerilog Parser.

A recursive-descent parser on top of the token stream of [tokenize][hdl_parser._sv.tokenizer.tokenize].

The parser is tolerant by design. It does not try to understand all of SystemVerilog, just the constructs
it extracts information from. Everything else is skipped:

* brackets are always consumed as balanced groups,
* unknown module items are skipped up to their terminating `;`,
* procedural code and other blocks are skipped up to their closing keyword,
* nothing is ever skipped beyond `endmodule`.

Supporting a new construct means adding one branch to the related `_parse_*` function. Module items are
dispatched by their leading keyword: a new one is a function decorated with `_handles`.
"""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from .. import datamodel as dm  # noqa: TID252
from .._diagnostics import Diagnostics, shorten  # noqa: TID252
from .._tokens import EOF, ID, KW, OPEN, Cursor, SourceMap, Token  # noqa: TID252
from .preproc import Macros, expand_mapped, split_args
from .tokenizer import MACRO, TYPE_KEYWORDS, tokenize

LOGGER = logging.getLogger(__name__)

# Parsing never continues beyond these keywords
_MODULE_START = frozenset(("module", "macromodule"))
_MODULE_END = frozenset(("endmodule", "endinterface"))
_UNIT_START = frozenset((*_MODULE_START, "package"))
# `interface` is no hard stop: it is used within modules too (`virtual interface`, interface ports)
_HARD_STOPS = frozenset((*_UNIT_START, "endmodule", "endpackage", "endinterface"))

_DIRECTIONS = frozenset(("input", "output", "inout"))
_MODPORT_DIRECTIONS = frozenset(("input", "output", "inout", "ref"))
_PARAMS = frozenset(("parameter", "localparam"))
_SIGNING = frozenset(("signed", "unsigned"))
_STRUCT_QUALIFIERS = frozenset(("packed", "signed", "unsigned", "tagged", "soft"))
_SEMI = frozenset((";",))
_COMMA = frozenset((",",))
_LABEL_OR_SEMI = frozenset((";", ":"))
# A parameter or port default ends here. Keywords are included to survive missing separators.
_VALUE_STOPS = frozenset((",", ";", *_PARAMS, *_DIRECTIONS))

_ALWAYS = frozenset(("always", "always_comb", "always_ff", "always_latch"))
_PROCEDURES = frozenset(("initial", "final"))
_EDGES = frozenset(("posedge", "negedge", "edge"))
_ASSERTIONS = frozenset(("assert", "assume", "cover", "restrict", "expect"))
_CONDITIONALS = frozenset(("if", "for"))
_CASE_GENERATES = frozenset(("case", "casex", "casez"))
_CASES = frozenset(("case", "casex", "casez", "randcase"))
_LOOPS = frozenset(("for", "while", "repeat", "foreach", "wait"))
_PREFIXES = frozenset(("unique", "unique0", "priority", "forever", "else"))
_JOINS = frozenset(("join", "join_any", "join_none"))
_LABELED = frozenset(("generate", "endgenerate"))
# Blocks without anything to extract: start keyword -> end keyword
_BLOCKS = {
    "class": "endclass",
    "covergroup": "endgroup",
    "property": "endproperty",
    "sequence": "endsequence",
    "specify": "endspecify",
    "clocking": "endclocking",
    "checker": "endchecker",
    "table": "endtable",
}
# Module items without anything to extract, which end with `;`
_DECLARATIONS = frozenset(
    (
        # fmt: off
        "alias",
        "assign",
        "automatic",
        "bind",
        "deassign",
        "defparam",
        "disable",
        "export",
        "extern",
        "force",
        "genvar",
        "import",
        "interconnect",
        "let",
        "nettype",
        "rand",
        "release",
        "specparam",
        "static",
        "timeprecision",
        "timeunit",
        "virtual",
        # gates and switches
        "and",
        "buf",
        "bufif0",
        "bufif1",
        "cmos",
        "nand",
        "nmos",
        "nor",
        "not",
        "notif0",
        "notif1",
        "or",
        "pmos",
        "pulldown",
        "pullup",
        "rcmos",
        "rnmos",
        "rpmos",
        "rtran",
        "rtranif0",
        "rtranif1",
        "tran",
        "tranif0",
        "tranif1",
        "xnor",
        "xor",
        # fmt: on
    )
)


# All items know their `first` and `last` token: the source range they are parsed from.
# Items with a name know its token as `name`.


class _Decl(NamedTuple):
    """One Declared Name (Port or Parameter). `first` and `last` span the whole declaration."""

    first: Token
    last: Token
    name: Token
    kind: str  # port direction or parameter keyword
    ptype: str
    dtype: str
    dim: str
    dim_unpacked: str
    default: str
    comment: list[str]


class _Con(NamedTuple):
    """One Connection Of An Instance."""

    first: Token
    last: Token
    port: str
    con: str
    comment: list[str]


class _Inst(NamedTuple):
    """One Instance. `first` and `last` span the whole instantiation."""

    first: Token
    last: Token
    name: Token
    module: Token
    generates: tuple[dm.Generate, ...]
    dim: str
    params: list[_Con]
    cons: list[_Con]


class _Macro(NamedTuple):
    """Macro Call Within The Module Header, Which Has Not Been Expanded."""

    first: Token
    last: Token
    call: dm.MacroCall


class _Typedef(NamedTuple):
    """One Type. `first` and `last` span the whole `typedef`."""

    first: Token
    last: Token
    name: Token
    kind: str  # alias, enum, struct or union
    dtype: str
    dim: str
    dim_unpacked: str
    members: list[_Decl]
    comment: list[str]


class _Function(NamedTuple):
    """One Function Or Task. `first` and `last` span it from `function` to `endfunction`."""

    first: Token
    last: Token
    name: Token
    kind: str  # function or task
    rtype: str
    dim: str
    args: list[_Decl]
    comment: list[str]


class _Process(NamedTuple):
    """One `always` Block. `first` and `last` span the whole block."""

    first: Token
    last: Token
    name: str
    events: list[dm.Event]
    # identifiers within the condition of the leading `if`
    checked: frozenset[str]
    generates: tuple[dm.Generate, ...]
    comment: list[str]


@dataclass
class _Package:
    """One Package. `last` is known as soon as the package is parsed completely."""

    first: Token
    last: Token
    name: Token
    params: list[_Decl] = field(default_factory=list)
    typedefs: list[_Typedef] = field(default_factory=list)
    functions: list[_Function] = field(default_factory=list)
    # there is an `endpackage`
    ended: bool = False


class _Modport(NamedTuple):
    """One Modport. `first` and `last` span the whole `modport` statement."""

    first: Token
    last: Token
    name: Token
    ports: list[_Decl]
    comment: list[str]


@dataclass
class _Module:
    """One Module Or Interface. `last` is known as soon as the module is parsed completely."""

    first: Token
    last: Token
    name: Token
    modports: list[_Modport] = field(default_factory=list)
    # there is an `endmodule`
    ended: bool = False
    params: list[_Decl] = field(default_factory=list)
    ports: list[_Decl] = field(default_factory=list)
    # signals with the generate constructs around
    signals: list[tuple[_Decl, tuple[dm.Generate, ...]]] = field(default_factory=list)
    typedefs: list[_Typedef] = field(default_factory=list)
    functions: list[_Function] = field(default_factory=list)
    processes: list[_Process] = field(default_factory=list)
    insts: list[_Inst] = field(default_factory=list)
    macros: list[_Macro] = field(default_factory=list)
    # token ranges within the header, which are not understood
    skipped: list[tuple[int, int]] = field(default_factory=list)
    # generate constructs around the current position, and whether they end with the next item (no `begin`)
    generates: list[dm.Generate] = field(default_factory=list)
    single: list[bool] = field(default_factory=list)

    def open_generate(self, generate: dm.Generate, single: bool = False) -> None:
        """Enter `generate`. `single`: it has no `begin` and ends with the next item."""
        self.generates.append(generate)
        self.single.append(single)

    def close_generate(self, kind: str | None = None) -> None:
        """Leave the innermost block (of `kind`, if given)."""
        self.close_single()
        if self.generates and kind in (None, self.generates[-1].kind):
            self.generates.pop()
            self.single.pop()
            # constructs without `begin` end with their block: if (A) for (...) begin ... end
            self.close_single()

    def close_single(self) -> None:
        """Leave all constructs, which end with the item parsed last."""
        while self.single and self.single[-1]:
            self.generates.pop()
            self.single.pop()


# --- types and declarations ---


def _type_ref_end(c: Cursor, idx: int) -> int:
    """Index behind a user-defined type at `idx`. Zero, if the identifier at `idx` is a name and not a type.

    A type is `my_t`, `pkg::my_t`, `my_if.modport` or `cls#(8)::my_t`, followed by optional dimensions and a name.
    """
    toks = c.toks
    if toks[idx].kind != ID:
        return 0
    idx += 1
    while True:
        if toks[idx].text == "#" and toks[idx + 1].text == "(":
            idx = c.match(idx + 1)
        if toks[idx].text in ("::", ".") and toks[idx + 1].kind == ID:
            idx += 2
        else:
            break
    end = idx
    while toks[idx].text == "[":
        idx = c.match(idx)
    return end if toks[idx].kind == ID else 0


def _parse_type(c: Cursor) -> tuple[str, str]:  # noqa: C901, PLR0912
    """Parse optional data type and return `(ptype, dtype)`."""
    ptype = dtype = ""
    while True:
        tok = c.peek()
        text = tok.text
        if tok.kind == KW:
            if text in _SIGNING:
                c.next()
                dtype = text
            elif text in TYPE_KEYWORDS:
                c.next()
                ptype = text
                if text == "type" and c.peek().text == "(":
                    c.skip_balanced()
            elif text == "interface":
                # generic interface port: interface[.modport] name
                start = c.pos
                c.next()
                if c.peek().text == "." and c.peek(1).kind == ID:
                    c.next()
                    c.next()
                ptype = c.text(start, c.pos)
            elif text in ("struct", "union", "enum"):
                c.next()
                ptype = text
                # qualifiers and enum base type
                while c.peek().text not in ("{", ",", ";", ")", "=") and c.peek().kind != EOF:
                    if c.peek().text == "[":
                        c.skip_balanced()
                    else:
                        c.next()
                if c.peek().text == "{":
                    c.skip_balanced()
            else:
                break
        elif tok.kind == ID:
            end = _type_ref_end(c, c.pos)
            if end:
                ptype = c.text(c.pos, end)
                c.skip_to(end)
            break
        elif tok.kind == MACRO:
            # type given by macro: `MY_T name
            end = c.pos + 1
            if c.toks[end].text == "(":
                end = c.match(end)
            if c.toks[end].kind != ID and c.toks[end].text != "[":
                break
            ptype = c.text(c.pos, end)
            c.skip_to(end)
        else:
            break
    return ptype, dtype


def _parse_dims(c: Cursor) -> str:
    """Parse optional dimensions."""
    if c.peek().text != "[":
        return ""
    start = c.pos
    while c.peek().text == "[":
        c.skip_balanced()
    return c.text(start, c.pos)


def _parse_decl(c: Cursor, kind: str) -> list[_Decl]:
    """Parse `[type] [dims] name [dims] [= default] {, name [dims] [= default]}`."""
    decls: list[_Decl] = []
    comment = c.start_comment()
    first = c.peek()
    if c.peek().text in _DIRECTIONS or c.peek().text in _PARAMS:
        kind = c.next().text
        ptype, dtype = _parse_type(c)
    else:
        ptype, dtype = _parse_type(c)
        if "." in ptype or ptype == "interface":
            # interface port: my_if.modport name
            kind = ""
    dim = _parse_dims(c)
    while c.peek().kind == ID:
        tok = c.next()
        dim_unpacked = _parse_dims(c)
        default = ""
        if c.accept("="):
            start = c.pos
            c.skip_until(_VALUE_STOPS)
            default = c.text(start, c.pos).strip()
        decls.append(_Decl(first, tok, tok, kind, ptype, dtype, dim, dim_unpacked, default, comment))
        # another name of this declaration, or the next declaration?
        if c.peek().text == "," and c.peek(1).kind == ID and not _type_ref_end(c, c.pos + 1):
            c.next()
        else:
            break
    return _set_last(c, decls)


def _set_last(c: Cursor, items: list) -> list:
    """Let all `items` end at the last consumed token."""
    last = c.toks[c.pos - 1] if c.pos else c.toks[0]
    return [item._replace(last=last) for item in items]


def _parse_macro_call(c: Cursor) -> _Macro:
    """Parse `` `NAME `` or `` `NAME(arguments) `` at the current position."""
    tok = c.next()
    args = None
    if c.peek().text == "(":
        start = c.pos + 1
        c.skip_balanced()
        args = tuple(split_args(c.text(start, c.pos - 1)))
    return _Macro(tok, c.toks[c.pos - 1], dm.MacroCall(name=tok.text[1:], args=args, ifdefs=tok.ifdefs))


def _parse_decl_list(c: Cursor, kind: str, mod: _Module) -> list[_Decl]:
    """Parse the parenthesized, comma separated parameter or port declarations of a module header.

    Macros which have not been expanded and stand for declarations are added to `mod.macros`,
    anything else which is not understood to `mod.skipped`.
    """
    decls: list[_Decl] = []
    opening = c.next()
    while True:
        tok = c.peek()
        if tok.text == ")":
            c.next()
            break
        if tok.kind == EOF or (tok.text in _HARD_STOPS and tok.kind == KW):
            c.unclosed.append(opening)
            break
        pos = c.pos
        if tok.text == ",":
            c.next()
        elif tok.text == ".":
            # explicit port: .name(expression)
            c.next()
            c.next()
        else:
            items = _parse_decl(c, kind)
            if items:
                # direction and parameter keyword are inherited by the following declarations
                kind = items[-1].kind
                decls += items
        if c.pos == pos:
            _parse_unknown(c, mod)
    c.sink = None
    return decls


def _parse_unknown(c: Cursor, mod: _Module) -> None:
    """Consume something within the module header, which is no declaration."""
    pos = c.pos
    tok = c.peek()
    if tok.kind == MACRO:
        mod.macros.append(_parse_macro_call(c))
        return
    if tok.text in OPEN:
        c.skip_balanced()
    else:
        c.next()
    if mod.skipped and mod.skipped[-1][1] == pos:
        # continued
        mod.skipped[-1] = (mod.skipped[-1][0], c.pos)
    else:
        mod.skipped.append((pos, c.pos))


def _parse_item_decl(c: Cursor) -> list[_Decl]:
    """Parse parameter or port declaration within the module body."""
    decls = _parse_decl(c, "")
    c.skip_until(_SEMI)
    c.accept(";")
    c.sink = None
    return _set_last(c, decls)


# --- types ---


def _parse_enum_members(c: Cursor) -> list[_Decl]:
    """Parse `{ name [range] [= value] {, name [range] [= value]} }`."""
    members: list[_Decl] = []
    opening = c.next()
    while True:
        tok = c.peek()
        if tok.text == "}":
            c.next()
            break
        if tok.kind == EOF or (tok.text in _HARD_STOPS and tok.kind == KW):
            c.unclosed.append(opening)
            break
        if tok.kind != ID:
            c.next()
            continue
        comment = c.start_comment()
        name = c.next()
        dim_unpacked = _parse_dims(c)
        value = ""
        if c.accept("="):
            start = c.pos
            c.skip_until(_COMMA)
            value = c.text(start, c.pos).strip()
        members.append(_Decl(name, c.toks[c.pos - 1], name, "", "", "", "", dim_unpacked, value, comment))
    return members


def _parse_struct_members(c: Cursor) -> list[_Decl]:
    """Parse `{ type [dims] name [dims] {, name [dims]} [= default]; ... }`."""
    members: list[_Decl] = []
    opening = c.next()
    while True:
        tok = c.peek()
        if tok.text == "}":
            c.next()
            break
        if tok.kind == EOF or (tok.text in _HARD_STOPS and tok.kind == KW):
            c.unclosed.append(opening)
            break
        pos = c.pos
        if tok.text != ";":
            members += _parse_decl(c, "")
            c.skip_until(_SEMI)
        if c.pos == pos:
            c.next()
    return members


def _parse_typedef(c: Cursor) -> _Typedef | None:
    """Parse `typedef type [dims] name [dims];`. The type may be an enumeration, struct or union.

    Forward declarations (`typedef name;`, `typedef class name;`) are no types on their own.
    """
    # the comments in front describe the type
    leading = list(c.comments.get(c.pos, ()))
    comment = c.start_comment()
    comment += leading
    first = c.next()
    kind = c.peek().text
    members: list[_Decl] = []
    if kind in ("enum", "struct", "union"):
        c.next()
        # base type of the enumeration, or qualifiers of the struct
        start = c.pos
        while c.peek().kind in (KW, ID) or c.peek().text == "::":
            c.next()
        dtype = c.text(start, c.pos)
        dim = _parse_dims(c)
        if c.peek().text == "{":
            members = _parse_enum_members(c) if kind == "enum" else _parse_struct_members(c)
            c.sink = comment
    else:
        kind = "alias"
        ptype, signing = _parse_type(c)
        dtype = f"{ptype} {signing}".strip()
        dim = _parse_dims(c)
    name = c.peek()
    typedef = None
    if name.kind == ID and (dtype or members):
        c.next()
        typedef = _Typedef(first, name, name, kind, dtype, dim, _parse_dims(c), members, comment)
    c.skip_until(_SEMI)
    c.accept(";")
    c.sink = None
    return typedef._replace(last=c.toks[c.pos - 1]) if typedef else None


# --- functions and tasks ---


def _parse_args(c: Cursor) -> list[_Decl]:
    """Parse the parenthesized arguments of a function or task. The direction is `input` by default."""
    args: list[_Decl] = []
    opening = c.next()
    direction = "input"
    while True:
        tok = c.peek()
        if tok.text == ")":
            c.next()
            break
        if tok.kind == EOF or (tok.text in _HARD_STOPS and tok.kind == KW):
            c.unclosed.append(opening)
            break
        pos = c.pos
        if tok.text == "const" and c.peek(1).text == "ref":
            c.next()
        if c.accept("ref"):
            direction = "ref"
        if c.peek().text != ",":
            items = _parse_decl(c, direction)
            if items:
                # the direction is inherited by the following arguments
                direction = items[-1].kind
                args += items
        if c.pos == pos:
            # separator, or nothing we understand
            if tok.text in OPEN:
                c.skip_balanced()
            else:
                c.next()
    return args


def _parse_function_body(c: Cursor, end: str) -> list[_Decl]:
    """Consume the body of a function or task up to `end`. Return the arguments declared within (`input a;`)."""
    args: list[_Decl] = []
    while True:
        tok = c.peek()
        if tok.kind == EOF or (tok.text in _HARD_STOPS and tok.kind == KW):
            break
        if tok.kind == KW and tok.text == end:
            c.next()
            _skip_label(c)
            break
        if tok.kind == KW and tok.text in _DIRECTIONS:
            args += _parse_item_decl(c)
        elif tok.text in OPEN:
            c.skip_balanced()
        else:
            c.next()
    return args


def _parse_function(c: Cursor) -> _Function | None:
    """Parse `function [type] name [(arguments)]; ... endfunction`. Likewise tasks.

    Arguments are declared in the parenthesis, or within the body (`input a;`).
    """
    # the comments in front describe the function
    leading = list(c.comments.get(c.pos, ()))
    comment = c.start_comment()
    comment += leading
    first = c.next()
    while c.peek().text in ("automatic", "static"):
        c.next()
    ptype, signing = _parse_type(c)
    dim = _parse_dims(c)
    # the name of a method defined outside of its class has a scope: cls::name
    while c.peek().kind == ID and c.peek(1).text in ("::", ".") and c.peek(2).kind == ID:
        c.next()
        c.next()
    name = c.peek()
    args: list[_Decl] = []
    if name.kind == ID:
        c.next()
        if c.peek().text == "(":
            args = _parse_args(c)
    c.sink = None
    args += _parse_function_body(c, f"end{first.text}")
    if name.kind != ID:
        return None
    rtype = f"{ptype} {signing}".strip()
    return _Function(first, c.toks[c.pos - 1], name, first.text, rtype, dim, args, comment)


# --- instances ---


def _is_instance(c: Cursor) -> bool:
    """Check for `module_name [#(...)] instance_name [dims] (` at the current position."""
    toks = c.toks
    idx = c.pos + 1
    if toks[idx].text == "#":
        if toks[idx + 1].text != "(":
            return False
        idx = c.match(idx + 1)
    if toks[idx].kind != ID:
        return False
    idx += 1
    while toks[idx].text == "[":
        idx = c.match(idx)
    return toks[idx].text == "("


def _parse_connections(c: Cursor) -> list[_Con]:
    """Parse the parenthesized connections or parameter values of an instance."""
    cons: list[_Con] = []
    opening = c.next()
    while True:
        tok = c.peek()
        text = tok.text
        if text == ")":
            c.next()
            break
        if tok.kind == EOF or (text in _HARD_STOPS and tok.kind == KW):
            c.unclosed.append(opening)
            break
        if text == ",":
            c.next()
        elif text == ".":
            c.next()
            port = c.next()
            if port.kind != ID:
                # .* or garbage
                continue
            comment = c.start_comment()
            if c.peek().text == "(":
                start = c.pos + 1
                c.skip_balanced()
                cons.append(_Con(tok, c.toks[c.pos - 1], port.text, c.text(start, c.pos - 1).strip(), comment))
            else:
                cons.append(_Con(tok, port, port.text, port.text, comment))
        else:
            # connection by order
            pos = c.pos
            comment = c.start_comment()
            c.skip_until(_COMMA)
            if c.pos == pos:
                c.next()
            else:
                cons.append(_Con(tok, c.toks[c.pos - 1], "", c.text(pos, c.pos).strip(), comment))
    return cons


def _parse_instances(c: Cursor, generates: tuple[dm.Generate, ...]) -> list[_Inst]:
    """Parse `module_name [#(...)] instance_name [dims] (...) {, instance_name [dims] (...)};`."""
    insts: list[_Inst] = []
    c.sink = None
    module = c.next()
    params = _parse_connections(c) if c.accept("#") else []
    while True:
        name = c.next()
        dim = _parse_dims(c)
        insts.append(_Inst(module, name, name, module, generates, dim, params, _parse_connections(c)))
        if c.peek().text == "," and c.peek(1).kind == ID:
            c.next()
        else:
            break
    c.accept(";")
    c.sink = None
    return _set_last(c, insts)


# --- code without anything to extract ---


def _skip_label(c: Cursor) -> str:
    """Consume optional label: `begin : label`. Return the label."""
    if c.peek().text == ":" and c.peek(1).kind == ID:
        c.next()
        return c.next().text
    return ""


def _skip_statement(c: Cursor) -> None:  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Skip one procedural statement."""
    while True:
        tok = c.peek()
        text = tok.text
        if tok.kind == EOF:
            return
        if tok.kind != KW:
            if tok.kind == ID and c.peek(1).text == ":":
                # label
                c.next()
                c.next()
            elif text in ("@", "#"):
                # event or delay control
                c.next()
                if c.peek().text == "(":
                    c.skip_balanced()
                else:
                    c.next()
            else:
                c.skip_until(_SEMI)
                c.accept(";")
                return
        elif text in _HARD_STOPS or text in _JOINS or text in ("end", "endcase"):
            return
        elif text == "begin":
            c.skip_past(frozenset(("end",)), frozenset(("begin",)))
            _skip_label(c)
            return
        elif text == "if":
            c.next()
            if c.peek().text == "(":
                c.skip_balanced()
            _skip_statement(c)
            if not c.accept("else"):
                return
        elif text in _LOOPS:
            c.next()
            if c.peek().text == "(":
                c.skip_balanced()
            elif text == "wait":
                # wait fork;
                c.skip_until(_SEMI)
        elif text in _PREFIXES:
            c.next()
        elif text in _CASES:
            c.skip_past(frozenset(("endcase",)), _CASES)
            return
        elif text == "fork":
            c.skip_past(_JOINS, frozenset(("fork",)))
            return
        elif text == "do":
            c.next()
            _skip_statement(c)
            c.skip_until(_SEMI)
            c.accept(";")
            return
        elif text in _ASSERTIONS:
            c.next()
            while c.peek().text in ("property", "sequence", "final", "#", "0"):
                c.next()
            if c.peek().text == "(":
                c.skip_balanced()
            if c.accept("else"):
                continue
            if c.accept(";"):
                return
            _skip_statement(c)
            if not c.accept("else"):
                return
        else:
            c.skip_until(_SEMI)
            c.accept(";")
            return


# --- module ---


_BodyHandler = Callable[[Cursor, _Module], None]
# Module item parsers by their leading keyword
_BODY_HANDLERS: dict[str, _BodyHandler] = {}


def _handles(*keywords: str) -> Callable[[_BodyHandler], _BodyHandler]:
    """Register the decorated function as parser of the module items starting with one of `keywords`."""

    def decorator(func: _BodyHandler) -> _BodyHandler:
        for keyword in keywords:
            if keyword in _BODY_HANDLERS:
                raise ValueError(f"Duplicate handler for {keyword!r}")
            _BODY_HANDLERS[keyword] = func
        return func

    return decorator


@_handles(*_DIRECTIONS)
def _handle_port(c: Cursor, mod: _Module) -> None:
    mod.ports.extend(_parse_item_decl(c))


@_handles(*_PARAMS)
def _handle_param(c: Cursor, mod: _Module) -> None:
    mod.params.extend(_parse_item_decl(c))


def _parse_modport_ports(c: Cursor) -> list[_Decl]:
    """Parse `( direction name {, name} {, direction name ...} )` of a modport.

    Imported and exported tasks and functions, and clocking blocks are skipped.
    """
    ports: list[_Decl] = []
    opening = c.next()
    direction = ""
    while True:
        tok = c.peek()
        text = tok.text
        if text == ")":
            c.next()
            break
        if tok.kind == EOF or (text in _HARD_STOPS and tok.kind == KW):
            c.unclosed.append(opening)
            break
        if text in OPEN:
            # arguments of an imported task or function, or the expression of `.name(expression)`
            c.skip_balanced()
            continue
        c.next()
        if tok.kind == KW:
            # input, output, inout or ref. Anything else (import, export, clocking) has no direction
            direction = text if text in _MODPORT_DIRECTIONS else ""
        elif tok.kind == ID and direction:
            ports.append(_Decl(tok, tok, tok, direction, "", "", "", "", "", []))
    return ports


@_handles("modport")
def _handle_modport(c: Cursor, mod: _Module) -> None:
    """`modport name (...) {, name (...)};`."""
    # the comments in front describe the (first) modport
    leading = list(c.comments.get(c.pos, ()))
    first = c.next()
    modports: list[_Modport] = []
    while c.peek().kind == ID:
        comment = c.start_comment()
        if not modports:
            comment += leading
        name = c.next()
        ports = _parse_modport_ports(c) if c.peek().text == "(" else []
        modports.append(_Modport(first, name, name, ports, comment))
        if not c.accept(","):
            break
    c.skip_until(_SEMI)
    c.accept(";")
    c.sink = None
    mod.modports += _set_last(c, modports)


@_handles("typedef")
def _handle_typedef(c: Cursor, mod: _Module) -> None:
    typedef = _parse_typedef(c)
    if typedef:
        mod.typedefs.append(typedef)


@_handles(*_PROCEDURES)
def _handle_procedure(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    c.next()
    _skip_statement(c)


def _parse_events(c: Cursor) -> list[dm.Event]:
    """Parse the sensitivity list `@(posedge a or negedge b, c)`, `@*` or `@name` at the current position."""
    c.next()
    if c.peek().text != "(":
        tok = c.next()
        return [dm.Event(signal=tok.text)] if tok.kind == ID else []
    events: list[dm.Event] = []
    end = c.match(c.pos) - 1
    c.next()
    while c.pos < end:
        edge = c.next().text if c.peek().text in _EDGES else ""
        # the signal ends at `or`, `,` or the condition `iff`. Parenthesis around are of no interest: posedge (clk)
        while c.peek().text == "(" and c.toks[c.match(c.pos)].text in ("or", ",", "iff", ")"):
            c.next()
        start = c.pos
        while c.pos < end and c.peek().text not in ("or", ",", "iff", ")"):
            if c.peek().text in OPEN:
                c.skip_balanced()
            else:
                c.next()
        signal = c.text(start, c.pos).strip()
        if signal and signal != "*":
            events.append(dm.Event(edge=edge, signal=signal))  # type: ignore[arg-type]
        while c.pos < end and c.peek().text not in ("or", ","):
            c.next()
        if c.pos < end:
            c.next()
    c.skip_to(end + 1)
    return events


@_handles(*_ALWAYS)
def _handle_always(c: Cursor, mod: _Module) -> None:
    """`always[_ff|_comb|_latch] [@(events)] statement`."""
    # the comments in front describe the block
    comment = list(c.comments.get(c.pos, ()))
    first = c.next()
    events = _parse_events(c) if c.peek().text == "@" else []
    # label and leading `if`, without consuming them: begin [: label] if (condition)
    toks = c.toks
    idx = c.pos
    name = ""
    if toks[idx].text == "begin":
        idx += 1
        if toks[idx].text == ":" and toks[idx + 1].kind == ID:
            name = toks[idx + 1].text
            idx += 2
    checked: frozenset[str] = frozenset()
    if toks[idx].text == "if" and toks[idx + 1].text == "(":
        checked = frozenset(tok.text for tok in toks[idx + 2 : c.match(idx + 1)] if tok.kind == ID)
    _skip_statement(c)
    mod.processes.append(_Process(first, toks[c.pos - 1], name, events, checked, tuple(mod.generates), comment))


@_handles(*_ASSERTIONS)
def _handle_assertion(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    _skip_statement(c)


# Generate constructs: the items within are parsed like any other item. The module knows the constructs around.


def _parse_cond(c: Cursor) -> str:
    """Parse the optional parenthesized condition of a generate construct."""
    if c.peek().text != "(":
        return ""
    start = c.pos + 1
    c.skip_balanced()
    return c.text(start, c.pos - 1).strip()


def _open_generate(c: Cursor, mod: _Module, kind: dm.GenerateKind, cond: str = "") -> None:
    """Enter the generate construct `kind`: a block, if `begin` follows, or just the next item."""
    if c.accept("begin"):
        mod.open_generate(dm.Generate(kind=kind, name=_skip_label(c), cond=cond))
    else:
        mod.open_generate(dm.Generate(kind=kind, cond=cond), single=True)


@_handles(*_CONDITIONALS)
def _handle_conditional(c: Cursor, mod: _Module) -> None:
    """`if (...) [begin [: label]]` and `for (...) [begin [: label]]`."""
    kind: dm.GenerateKind = "if" if c.next().text == "if" else "for"
    _open_generate(c, mod, kind, _parse_cond(c))


@_handles("else")
def _handle_else(c: Cursor, mod: _Module) -> None:
    """`else [begin [: label]]`. The `if` of `else if` is a generate construct on its own."""
    c.next()
    if c.peek().text != "if":
        _open_generate(c, mod, "else")


@_handles(*_CASE_GENERATES)
def _handle_case(c: Cursor, mod: _Module) -> None:
    """`case (...)`, up to `endcase`."""
    c.next()
    mod.open_generate(dm.Generate(kind="case", cond=_parse_cond(c)))


@_handles("endcase")
def _handle_endcase(c: Cursor, mod: _Module) -> None:
    c.next()
    _skip_label(c)
    mod.close_generate("case")


@_handles("begin")
def _handle_begin(c: Cursor, mod: _Module) -> None:
    """`begin [: label]` on its own, i.e. as case item."""
    c.next()
    mod.open_generate(dm.Generate(kind="begin", name=_skip_label(c)))


@_handles("end")
def _handle_end(c: Cursor, mod: _Module) -> None:
    c.next()
    _skip_label(c)
    mod.close_generate()


@_handles(*_LABELED)
def _handle_labeled(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    c.next()
    _skip_label(c)


def _parse_signals(c: Cursor, mod: _Module) -> None:
    """Parse the declaration of nets or variables: `type [dims] name [dims] [= value] {, ...};`."""
    generates = tuple(mod.generates)
    mod.signals += [(decl, generates) for decl in _parse_item_decl(c)]


@_handles(*TYPE_KEYWORDS, "enum", "struct", "union")
def _handle_signal(c: Cursor, mod: _Module) -> None:
    _parse_signals(c, mod)


@_handles("function", "task")
def _handle_function(c: Cursor, mod: _Module) -> None:
    function = _parse_function(c)
    if function:
        mod.functions.append(function)


@_handles(*_BLOCKS)
def _handle_block(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    c.skip_past(frozenset((_BLOCKS[c.peek().text],)))


@_handles("default")
def _handle_default(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    """`default clocking cb;` and `default disable iff (rst);`."""
    c.next()
    if c.peek().text == "disable" or (c.peek().text == "clocking" and c.peek(2).text == ";"):
        c.skip_until(_SEMI)


@_handles(*_DECLARATIONS)
def _handle_declaration(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    c.skip_until(_SEMI)
    c.accept(";")


def _parse_identifier_item(c: Cursor, mod: _Module) -> None:
    """Parse module item starting with an identifier."""
    if c.peek(1).text == ":":
        # label of a generate block: label : begin
        name = c.next().text
        c.next()
        if c.accept("begin"):
            mod.open_generate(dm.Generate(kind="begin", name=_skip_label(c) or name))
    elif _is_instance(c):
        mod.insts.extend(_parse_instances(c, tuple(mod.generates)))
    elif _type_ref_end(c, c.pos):
        # signal of a user-defined type: my_t name;
        _parse_signals(c, mod)
    else:
        # statement, or the expression of a case-generate item
        c.skip_until(_LABEL_OR_SEMI)
        c.next()


def _parse_body(c: Cursor, mod: _Module) -> bool:  # noqa: C901
    """Parse module items up to `endmodule`. Return whether there is an `endmodule`.

    Items starting with a keyword are parsed by the related function of `_BODY_HANDLERS`.
    """
    handlers = _BODY_HANDLERS
    depth = 0
    while True:
        if len(mod.generates) == depth:
            # the item parsed last did not open a generate construct: it ends the ones without `begin`
            mod.close_single()
        depth = len(mod.generates)
        tok = c.peek()
        text = tok.text
        kind = tok.kind
        if kind == KW:
            if text in _MODULE_END:
                c.next()
                _skip_label(c)
                return True
            if text in _UNIT_START:
                # missing endmodule
                return False
            handler = handlers.get(text)
            if handler:
                handler(c, mod)
            else:
                c.next()
        elif kind == ID:
            _parse_identifier_item(c, mod)
        elif kind == EOF:
            return False
        elif text in OPEN:
            c.skip_balanced()
        else:
            c.next()
            if kind == MACRO and c.peek().text == "(":
                c.skip_balanced()


def _parse_module(c: Cursor) -> _Module | None:
    """Parse `module name [imports] [#(parameters)] [(ports)]; items endmodule`. Likewise interfaces."""
    start = c.next()
    while c.peek().text in ("static", "automatic"):
        c.next()
    if c.peek().kind != ID:
        return None
    name = c.next()
    mod = _Module(start, name, name)
    while c.peek().text == "import":
        c.skip_until(_SEMI)
        c.accept(";")
    if c.peek().text == "#" and c.peek(1).text == "(":
        c.next()
        mod.params.extend(_parse_decl_list(c, "parameter", mod))
    if c.peek().text == "(":
        # names of a non-ANSI port list have neither direction nor type
        mod.ports.extend(decl for decl in _parse_decl_list(c, "", mod) if decl.kind or decl.ptype)
    c.accept(";")
    mod.ended = _parse_body(c, mod)
    mod.last = c.toks[c.pos - 1]
    return mod


def _parse_package_item(c: Cursor, pkg: _Package) -> None:
    """Parse one item of a package."""
    tok = c.peek()
    text = tok.text
    if text in _PARAMS:
        pkg.params.extend(_parse_item_decl(c))
    elif text == "typedef":
        typedef = _parse_typedef(c)
        if typedef:
            pkg.typedefs.append(typedef)
    elif text in ("function", "task"):
        function = _parse_function(c)
        if function:
            pkg.functions.append(function)
    elif text in _BLOCKS and tok.kind == KW:
        # classes, ...
        c.skip_past(frozenset((_BLOCKS[text],)))
    else:
        # anything else: imports, variables, ...
        c.skip_until(_SEMI)
        c.accept(";")


def _parse_package(c: Cursor) -> _Package | None:
    """Parse `package name; items endpackage`."""
    start = c.next()
    while c.peek().text in ("static", "automatic"):
        c.next()
    if c.peek().kind != ID:
        return None
    name = c.next()
    pkg = _Package(start, name, name)
    c.accept(";")
    while True:
        tok = c.peek()
        if tok.kind == EOF or (tok.text in _UNIT_START and tok.kind == KW):
            # missing endpackage
            break
        if tok.text == "endpackage":
            c.next()
            _skip_label(c)
            pkg.ended = True
            break
        pos = c.pos
        _parse_package_item(c, pkg)
        if c.pos == pos:
            c.next()
    pkg.last = c.toks[c.pos - 1]
    return pkg


def _parse_units(c: Cursor) -> tuple[list[_Module], list[_Package]]:
    """Parse all modules and packages."""
    mods: list[_Module] = []
    pkgs: list[_Package] = []
    while True:
        tok = c.peek()
        if tok.kind == EOF:
            return mods, pkgs
        if tok.kind == KW and (tok.text in _MODULE_START or (tok.text == "interface" and c.peek(1).text != "class")):
            mod = _parse_module(c)
            if mod:
                mods.append(mod)
        elif tok.kind == KW and tok.text == "package":
            pkg = _parse_package(c)
            if pkg:
                pkgs.append(pkg)
        elif tok.text == "extern":
            c.skip_until(_SEMI)
            c.next()
        else:
            c.next()


# --- data model ---


def _create_params(decls: list[_Decl], kind: str, smap: SourceMap) -> tuple[dm.Param, ...]:
    return tuple(
        dm.Param(
            name=decl.name.text,
            ptype=decl.ptype,
            dtype=decl.dtype,
            dim=decl.dim,
            dim_unpacked=decl.dim_unpacked,
            default=decl.default,
            comment=tuple(decl.comment),
            ifdefs=decl.name.ifdefs,
            loc=smap.span(decl.first, decl.last, decl.name),
        )
        for decl in decls
        if decl.kind == kind
    )


def _create_modports(modports: list[_Modport], smap: SourceMap) -> tuple[dm.Modport, ...]:
    return tuple(
        dm.Modport(
            name=modport.name.text,
            ports=tuple(
                dm.Port(
                    name=port.name.text,
                    direction=port.kind,
                    ifdefs=port.name.ifdefs,
                    loc=smap.span(port.name, port.name),
                )
                for port in modport.ports
            ),
            comment=tuple(modport.comment),
            ifdefs=modport.name.ifdefs,
            loc=smap.span(modport.first, modport.last, modport.name),
        )
        for modport in modports
    )


def _create_typedefs(typedefs: list[_Typedef], smap: SourceMap) -> tuple[dm.Typedef, ...]:
    return tuple(
        dm.Typedef(
            name=typedef.name.text,
            kind=typedef.kind,  # type: ignore[arg-type]
            dtype=typedef.dtype,
            dim=typedef.dim,
            dim_unpacked=typedef.dim_unpacked,
            members=tuple(
                dm.Member(
                    name=member.name.text,
                    dtype=f"{member.ptype} {member.dtype}".strip(),
                    dim=member.dim,
                    dim_unpacked=member.dim_unpacked,
                    value=member.default,
                    comment=tuple(member.comment),
                    ifdefs=member.name.ifdefs,
                    loc=smap.span(member.first, member.last, member.name),
                )
                for member in typedef.members
            ),
            comment=tuple(typedef.comment),
            ifdefs=typedef.name.ifdefs,
            loc=smap.span(typedef.first, typedef.last, typedef.name),
        )
        for typedef in typedefs
    )


def _create_ports(decls: list[_Decl], smap: SourceMap) -> tuple[dm.Port, ...]:
    return tuple(
        dm.Port(
            name=decl.name.text,
            direction=decl.kind,
            ptype=decl.ptype,
            dtype=decl.dtype,
            dim=decl.dim,
            dim_unpacked=decl.dim_unpacked,
            default=decl.default,
            comment=tuple(decl.comment),
            ifdefs=decl.name.ifdefs,
            loc=smap.span(decl.first, decl.last, decl.name),
        )
        for decl in decls
    )


def _create_signals(mod: _Module, smap: SourceMap) -> tuple[dm.Signal, ...]:
    # Verilog declares the type of a port on its own: `output q; reg q;`. This is no signal.
    ports = {port.name.text for port in mod.ports}
    return tuple(
        dm.Signal(
            name=decl.name.text,
            ptype=decl.ptype,
            dtype=decl.dtype,
            dim=decl.dim,
            dim_unpacked=decl.dim_unpacked,
            default=decl.default,
            generates=generates,
            comment=tuple(decl.comment),
            ifdefs=decl.name.ifdefs,
            loc=smap.span(decl.first, decl.last, decl.name),
        )
        for decl, generates in mod.signals
        if decl.name.text not in ports
    )


def _create_processes(processes: list[_Process], smap: SourceMap) -> tuple[dm.Process, ...]:
    result = []
    for process in processes:
        # Clock and reset are never guessed: the reset is the edge checked by the leading `if`,
        # the clock is the one other edge.
        edges = [event for event in process.events if event.edge in ("posedge", "negedge")]
        resets = [event for event in edges if event.signal in process.checked] if len(edges) > 1 else []
        clocks = [event for event in edges if event not in resets[:1]]
        clock = clocks[0] if len(clocks) == 1 else None
        reset = resets[0] if resets and clock else None
        result.append(
            dm.Process(
                name=process.name,
                kind=process.first.text,  # type: ignore[arg-type]
                events=tuple(process.events),
                clock=clock.signal if clock else "",
                clock_edge=clock.edge if clock else "",
                reset=reset.signal if reset else "",
                reset_edge=reset.edge if reset else "",
                generates=process.generates,
                comment=tuple(process.comment),
                ifdefs=process.first.ifdefs,
                loc=smap.span(process.first, process.last),
            )
        )
    return tuple(result)


def _create_functions(functions: list[_Function], smap: SourceMap) -> tuple[dm.Function, ...]:
    return tuple(
        dm.Function(
            name=function.name.text,
            kind=function.kind,  # type: ignore[arg-type]
            rtype=function.rtype,
            dim=function.dim,
            args=_create_ports(function.args, smap),
            comment=tuple(function.comment),
            ifdefs=function.name.ifdefs,
            loc=smap.span(function.first, function.last, function.name),
        )
        for function in functions
    )


def _create_connections(cons: list[_Con], smap: SourceMap) -> tuple[dm.Connection, ...]:
    return tuple(
        dm.Connection(
            port=con.port,
            con=con.con,
            comment=tuple(con.comment),
            ifdefs=con.first.ifdefs,
            loc=smap.span(con.first, con.last),
        )
        for con in cons
    )


def _create_insts(insts: list[_Inst], smap: SourceMap) -> tuple[dm.ModuleInstance, ...]:
    return tuple(
        dm.ModuleInstance(
            name=inst.name.text,
            module=inst.module.text,
            generates=inst.generates,
            dim=inst.dim,
            params=_create_connections(inst.params, smap),
            connections=_create_connections(inst.cons, smap),
            ifdefs=inst.module.ifdefs,
            loc=smap.span(inst.first, inst.last, inst.name),
        )
        for inst in insts
    )


def _create_macros(mod: _Module, smap: SourceMap) -> tuple[dm.MacroCall, ...]:
    return tuple(macro.call.model_copy(update={"loc": smap.span(macro.first, macro.last)}) for macro in mod.macros)


def _report(c: Cursor, mods: list[_Module], pkgs: list[_Package], smap: SourceMap, diagnostics: Diagnostics) -> None:
    """Report everything, which has not been parsed properly."""
    for pkg in pkgs:
        if not pkg.ended:
            diagnostics.add(
                "missing-end", f"package '{pkg.name.text}' has no 'endpackage'.", smap.span(pkg.first, pkg.name)
            )
    for mod in mods:
        # module or interface
        kind = mod.first.text
        name = mod.name.text
        for start, end in mod.skipped:
            diagnostics.add(
                "header-item-skipped",
                f"{kind} '{name}': '{shorten(c.text(start, end))}' in {kind} header is not understood. "
                "Ports or parameters may be missing.",
                smap.span(c.toks[start], c.toks[end - 1]),
            )
        if not mod.ended:
            diagnostics.add("missing-end", f"{kind} '{name}' has no 'end{kind}'.", smap.span(mod.first, mod.name))
    for tok in c.unclosed:
        diagnostics.add("unbalanced-bracket", f"'{tok.text}' is never closed.", smap.span(tok, tok))


def parse(  # noqa: PLR0913
    text: str,
    file_path: Path | None = None,
    expand_macros: bool = False,
    macros: Macros | None = None,
    inc_dirs: Iterable[Path] = (),
    resolve_ifdefs: bool = False,
    diagnostics: Diagnostics | None = None,
) -> dm.File:
    """Parse SystemVerilog `text` and return its modules, interfaces and packages.

    The result has neither path, nor identifiers, nor diagnostics.

    With `expand_macros`, macros are expanded upfront, if they are defined within `text`, within an included
    file or given by `macros`. Included files are searched next to `file_path` and in `inc_dirs`.
    With `resolve_ifdefs`, the `` `ifdef `` conditions on macros which are known to be defined are resolved.
    Problems are reported to `diagnostics`.
    """
    if diagnostics is None:
        diagnostics = Diagnostics(str(file_path) if file_path else "<text>")
    includes: list[Path] = []
    if expand_macros:
        text, smap = expand_mapped(
            text,
            macros=macros,
            file_path=file_path,
            inc_dirs=inc_dirs,
            resolve_ifdefs=resolve_ifdefs,
            diagnostics=diagnostics,
            includes=includes,
        )
    else:
        smap = SourceMap(text)
    c = Cursor(tokenize(text), _HARD_STOPS)
    mods, pkgs = _parse_units(c)
    _report(c, mods, pkgs, smap, diagnostics)
    packages = tuple(
        dm.Package(
            name=pkg.name.text,
            params=_create_params(pkg.params, "parameter", smap),
            localparams=_create_params(pkg.params, "localparam", smap),
            typedefs=_create_typedefs(pkg.typedefs, smap),
            functions=_create_functions(pkg.functions, smap),
            ifdefs=pkg.first.ifdefs,
            loc=smap.span(pkg.first, pkg.last, pkg.name),
        )
        for pkg in pkgs
    )
    modules = []
    interfaces = []
    for mod in mods:
        fields: dict[str, Any] = {
            "name": mod.name.text,
            "params": _create_params(mod.params, "parameter", smap),
            "localparams": _create_params(mod.params, "localparam", smap),
            "ports": _create_ports(mod.ports, smap),
            "signals": _create_signals(mod, smap),
            "typedefs": _create_typedefs(mod.typedefs, smap),
            "functions": _create_functions(mod.functions, smap),
            "processes": _create_processes(mod.processes, smap),
            "insts": _create_insts(mod.insts, smap),
            "ifdefs": mod.first.ifdefs,
            "unresolved_macros": _create_macros(mod, smap),
            "loc": smap.span(mod.first, mod.last, mod.name),
        }
        if mod.first.text == "interface":
            interfaces.append(dm.Interface(modports=_create_modports(mod.modports, smap), **fields))
        else:
            modules.append(dm.Module(**fields))
    return dm.File(
        path=None,
        includes=tuple(path.as_posix() for path in includes),
        modules=tuple(modules),
        interfaces=tuple(interfaces),
        packages=packages,
    )
