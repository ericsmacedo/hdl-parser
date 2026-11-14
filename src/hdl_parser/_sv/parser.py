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
from collections.abc import Callable
from typing import NamedTuple

from .. import datamodel as dm  # noqa: TID252
from .._tokens import EOF, ID, KW, OPEN, Cursor, Token  # noqa: TID252
from .preproc import Macros, expand, split_args
from .tokenizer import MACRO, TYPE_KEYWORDS, tokenize

LOGGER = logging.getLogger(__name__)

# Parsing never continues beyond these keywords
_MODULE_START = frozenset(("module", "macromodule"))
_HARD_STOPS = frozenset((*_MODULE_START, "endmodule"))

_DIRECTIONS = frozenset(("input", "output", "inout"))
_PARAMS = frozenset(("parameter", "localparam"))
_SIGNING = frozenset(("signed", "unsigned"))
_STRUCT_QUALIFIERS = frozenset(("packed", "signed", "unsigned", "tagged", "soft"))
_SEMI = frozenset((";",))
_COMMA = frozenset((",",))
_LABEL_OR_SEMI = frozenset((";", ":"))
# A parameter or port default ends here. Keywords are included to survive missing separators.
_VALUE_STOPS = frozenset((",", ";", *_PARAMS, *_DIRECTIONS))

_PROCEDURES = frozenset(("always", "always_comb", "always_ff", "always_latch", "initial", "final"))
_ASSERTIONS = frozenset(("assert", "assume", "cover", "restrict", "expect"))
_CONDITIONALS = frozenset(("if", "for", "case", "casex", "casez"))
_CASES = frozenset(("case", "casex", "casez", "randcase"))
_LOOPS = frozenset(("for", "while", "repeat", "foreach", "wait"))
_PREFIXES = frozenset(("unique", "unique0", "priority", "forever", "else"))
_JOINS = frozenset(("join", "join_any", "join_none"))
_LABELED = frozenset(("begin", "end", "generate", "endgenerate", "endcase"))
# Blocks without anything to extract: start keyword -> end keyword
_BLOCKS = {
    "function": "endfunction",
    "task": "endtask",
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
        *TYPE_KEYWORDS,
        "alias",
        "assign",
        "automatic",
        "bind",
        "deassign",
        "defparam",
        "disable",
        "enum",
        "export",
        "extern",
        "force",
        "genvar",
        "import",
        "interconnect",
        "let",
        "modport",
        "nettype",
        "rand",
        "release",
        "specparam",
        "static",
        "struct",
        "timeprecision",
        "timeunit",
        "typedef",
        "union",
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


class _Decl(NamedTuple):
    """One Declared Name (Port or Parameter)."""

    token: Token
    kind: str  # port direction or parameter keyword
    ptype: str
    dtype: str
    dim: str
    dim_unpacked: str
    default: str
    comment: list[str]


class _Con(NamedTuple):
    token: Token
    port: str
    con: str
    comment: list[str]


class _Inst(NamedTuple):
    module: Token
    name: Token
    cons: list[_Con]


class _Module(NamedTuple):
    token: Token
    name: str
    params: list[_Decl]
    ports: list[_Decl]
    insts: list[_Inst]
    macros: list[dm.MacroCall]


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
    if c.peek().text in _DIRECTIONS or c.peek().text in _PARAMS:
        kind = c.next().text
        ptype, dtype = _parse_type(c)
    else:
        ptype, dtype = _parse_type(c)
        if "." in ptype:
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
        decls.append(_Decl(tok, kind, ptype, dtype, dim, dim_unpacked, default, comment))
        # another name of this declaration, or the next declaration?
        if c.peek().text == "," and c.peek(1).kind == ID and not _type_ref_end(c, c.pos + 1):
            c.next()
        else:
            break
    return decls


def _parse_macro_call(c: Cursor) -> dm.MacroCall:
    """Parse `` `NAME `` or `` `NAME(arguments) `` at the current position."""
    tok = c.next()
    args = None
    if c.peek().text == "(":
        start = c.pos + 1
        c.skip_balanced()
        args = tuple(split_args(c.text(start, c.pos - 1)))
    return dm.MacroCall(name=tok.text[1:], args=args, ifdefs=tok.ifdefs)


def _parse_decl_list(c: Cursor, kind: str, macros: list[dm.MacroCall]) -> list[_Decl]:
    """Parse the parenthesized, comma separated parameter or port declarations of a module header.

    Macros which have not been expanded and stand for declarations are added to `macros`.
    """
    decls: list[_Decl] = []
    c.next()
    while True:
        tok = c.peek()
        if tok.text == ")":
            c.next()
            break
        if tok.kind == EOF or (tok.text in _HARD_STOPS and tok.kind == KW):
            break
        pos = c.pos
        if tok.text == ".":
            # explicit port: .name(expression)
            c.next()
            c.next()
        elif tok.text != ",":
            items = _parse_decl(c, kind)
            if items:
                # direction and parameter keyword are inherited by the following declarations
                kind = items[-1].kind
                decls += items
        if c.pos == pos:
            # nothing we understand
            if tok.kind == MACRO:
                macros.append(_parse_macro_call(c))
            elif tok.text in OPEN:
                c.skip_balanced()
            else:
                c.next()
    c.sink = None
    return decls


def _parse_item_decl(c: Cursor) -> list[_Decl]:
    """Parse parameter or port declaration within the module body."""
    decls = _parse_decl(c, "")
    c.skip_until(_SEMI)
    c.accept(";")
    c.sink = None
    return decls


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
    """Parse the parenthesized connections of an instance."""
    cons: list[_Con] = []
    c.next()
    while True:
        tok = c.peek()
        text = tok.text
        if text == ")":
            c.next()
            break
        if tok.kind == EOF or (text in _HARD_STOPS and tok.kind == KW):
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
                cons.append(_Con(tok, port.text, c.text(start, c.pos - 1).strip(), comment))
            else:
                cons.append(_Con(tok, port.text, port.text, comment))
        else:
            # connection by order
            pos = c.pos
            comment = c.start_comment()
            c.skip_until(_COMMA)
            if c.pos == pos:
                c.next()
            else:
                cons.append(_Con(tok, "", c.text(pos, c.pos).strip(), comment))
    return cons


def _parse_instances(c: Cursor) -> list[_Inst]:
    """Parse `module_name [#(...)] instance_name [dims] (...) {, instance_name [dims] (...)};`."""
    insts: list[_Inst] = []
    c.sink = None
    module = c.next()
    if c.accept("#"):
        c.skip_balanced()
    while True:
        name = c.next()
        while c.peek().text == "[":
            c.skip_balanced()
        insts.append(_Inst(module, name, _parse_connections(c)))
        if c.peek().text == "," and c.peek(1).kind == ID:
            c.next()
        else:
            break
    c.accept(";")
    c.sink = None
    return insts


# --- code without anything to extract ---


def _skip_label(c: Cursor) -> None:
    """Consume optional label: `begin : label`."""
    if c.peek().text == ":" and c.peek(1).kind == ID:
        c.next()
        c.next()


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


@_handles(*_PROCEDURES)
def _handle_procedure(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    c.next()
    _skip_statement(c)


@_handles(*_ASSERTIONS)
def _handle_assertion(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    _skip_statement(c)


@_handles(*_CONDITIONALS)
def _handle_conditional(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    """Generate construct: the items within are parsed like any other item."""
    c.next()
    if c.peek().text == "(":
        c.skip_balanced()


@_handles(*_LABELED)
def _handle_labeled(c: Cursor, mod: _Module) -> None:  # noqa: ARG001
    c.next()
    _skip_label(c)


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
        # label
        c.next()
        c.next()
    elif _is_instance(c):
        mod.insts.extend(_parse_instances(c))
    else:
        # declaration or statement, or the expression of a case-generate item
        c.skip_until(_LABEL_OR_SEMI)
        c.next()


def _parse_body(c: Cursor, mod: _Module) -> None:
    """Parse module items up to `endmodule`.

    Items starting with a keyword are parsed by the related function of `_BODY_HANDLERS`.
    """
    handlers = _BODY_HANDLERS
    while True:
        tok = c.peek()
        text = tok.text
        kind = tok.kind
        if kind == KW:
            if text == "endmodule":
                c.next()
                return
            if text in _MODULE_START:
                # missing endmodule
                return
            handler = handlers.get(text)
            if handler:
                handler(c, mod)
            else:
                c.next()
        elif kind == ID:
            _parse_identifier_item(c, mod)
        elif kind == EOF:
            return
        elif text in OPEN:
            c.skip_balanced()
        else:
            c.next()
            if kind == MACRO and c.peek().text == "(":
                c.skip_balanced()


def _parse_module(c: Cursor) -> _Module | None:
    """Parse `module name [imports] [#(parameters)] [(ports)]; items endmodule`."""
    start = c.next()
    while c.peek().text in ("static", "automatic"):
        c.next()
    if c.peek().kind != ID:
        return None
    mod = _Module(start, c.next().text, [], [], [], [])
    while c.peek().text == "import":
        c.skip_until(_SEMI)
        c.accept(";")
    if c.peek().text == "#" and c.peek(1).text == "(":
        c.next()
        mod.params.extend(_parse_decl_list(c, "parameter", mod.macros))
    if c.peek().text == "(":
        # names of a non-ANSI port list have neither direction nor type
        mod.ports.extend(decl for decl in _parse_decl_list(c, "", mod.macros) if decl.kind or decl.ptype)
    c.accept(";")
    _parse_body(c, mod)
    return mod


def _parse_modules(c: Cursor) -> list[_Module]:
    """Parse all modules."""
    mods: list[_Module] = []
    while True:
        tok = c.peek()
        if tok.kind == EOF:
            return mods
        if tok.kind == KW and tok.text in _MODULE_START:
            mod = _parse_module(c)
            if mod:
                mods.append(mod)
        elif tok.text == "extern":
            c.skip_until(_SEMI)
            c.next()
        else:
            c.next()


# --- data model ---


def _create_params(decls: list[_Decl], kind: str) -> tuple[dm.Param, ...]:
    return tuple(
        dm.Param(
            name=decl.token.text,
            ptype=decl.ptype,
            dim=decl.dim,
            dim_unpacked=decl.dim_unpacked,
            default=decl.default,
            comment=tuple(decl.comment),
            ifdefs=decl.token.ifdefs,
        )
        for decl in decls
        if decl.kind == kind
    )


def _create_ports(decls: list[_Decl]) -> tuple[dm.Port, ...]:
    return tuple(
        dm.Port(
            name=decl.token.text,
            direction=decl.kind,
            ptype=decl.ptype,
            dtype=decl.dtype,
            dim=decl.dim,
            dim_unpacked=decl.dim_unpacked,
            comment=tuple(decl.comment),
            ifdefs=decl.token.ifdefs,
        )
        for decl in decls
    )


def _create_insts(insts: list[_Inst]) -> tuple[dm.ModuleInstance, ...]:
    return tuple(
        dm.ModuleInstance(
            name=inst.name.text,
            module=inst.module.text,
            ifdefs=inst.module.ifdefs,
            connections=tuple(
                dm.Connection(port=con.port, con=con.con, comment=tuple(con.comment), ifdefs=con.token.ifdefs)
                for con in inst.cons
            ),
        )
        for inst in insts
    )


def _create_macros(mod: _Module, context: str) -> tuple[dm.MacroCall, ...]:
    for macro in mod.macros:
        LOGGER.warning(
            "%s: module '%s': unknown macro `%s in module header. Ports or parameters may be missing.",
            context,
            mod.name,
            macro.name,
        )
    return tuple(mod.macros)


def parse(text: str, macros: Macros | None = None, context: str = "") -> tuple[dm.Module, ...]:
    """Parse SystemVerilog `text` and return its modules.

    Macros are expanded upfront, if they are defined within `text` or given by `macros`.
    """
    context = context or "<text>"
    text = expand(text, macros=macros, context=context)
    return tuple(
        dm.Module(
            name=mod.name,
            params=_create_params(mod.params, "parameter"),
            localparams=_create_params(mod.params, "localparam"),
            ports=_create_ports(mod.ports),
            insts=_create_insts(mod.insts),
            ifdefs=mod.token.ifdefs,
            unresolved_macros=_create_macros(mod, context),
        )
        for mod in _parse_modules(Cursor(tokenize(text), _HARD_STOPS))
    )
