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

Supporting a new construct means adding one branch to the related `_parse_*` function.
"""

from bisect import bisect_left
from typing import NamedTuple

from .. import datamodel as dm  # noqa: TID252
from .tokenizer import EOF, ID, KW, MACRO, TYPE_KEYWORDS, Token, Tokens, tokenize

_OPEN = frozenset("([{")
_CLOSE = frozenset(")]}")
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


class Cursor:
    """Position Within The Token Stream.

    Comments are not part of the token stream. They are handed over to `sink` (if set), as soon as the token
    behind them is consumed. A declaration sets `sink` to its own comment list, to receive all comments up to
    the next declaration.
    """

    __slots__ = ("_gap_starts", "comments", "gaps", "last", "pos", "sink", "source", "toks")

    def __init__(self, tokens: Tokens):
        self.source = tokens.source
        self.toks = tokens.tokens
        self.comments = tokens.comments
        self.gaps = tokens.gaps
        self._gap_starts = [gap[0] for gap in tokens.gaps]
        self.last = len(self.toks) - 1
        self.pos = 0
        self.sink: list[str] | None = None

    def peek(self, offset: int = 0) -> Token:
        """Token at current position plus `offset`, without consuming it."""
        idx = self.pos + offset
        return self.toks[idx] if idx < self.last else self.toks[-1]

    def next(self) -> Token:
        """Consume one token."""
        pos = self.pos
        tok = self.toks[pos]
        if pos < self.last:
            if self.sink is not None and pos in self.comments:
                self.sink += self.comments[pos]
            self.pos = pos + 1
        return tok

    def accept(self, text: str) -> bool:
        """Consume next token if it is `text`."""
        if self.toks[self.pos].text == text:
            self.next()
            return True
        return False

    def start_comment(self) -> list[str]:
        """Start a new comment list. Pending comments still belong to the previous one."""
        pending = self.comments.pop(self.pos, None)
        if pending and self.sink is not None:
            self.sink += pending
        self.sink = []
        return self.sink

    def match(self, idx: int) -> int:
        """Index behind the bracket group starting at `idx`."""
        toks = self.toks
        depth = 0
        while True:
            tok = toks[idx]
            text = tok.text
            if text in _OPEN:
                depth += 1
            elif text in _CLOSE:
                depth -= 1
                if depth <= 0:
                    return idx + 1
            elif tok.kind == EOF or (text in _HARD_STOPS and tok.kind == KW):
                return idx
            idx += 1

    def skip_to(self, idx: int) -> None:
        """Consume all tokens up to `idx`."""
        if self.sink is None:
            self.pos = idx
        else:
            while self.pos < idx:
                self.next()

    def skip_balanced(self) -> None:
        """Consume the bracket group at the current position."""
        self.skip_to(self.match(self.pos))

    def skip_until(self, stops: frozenset[str]) -> None:
        """Consume tokens until one of `stops`. Bracket groups are skipped as a whole.

        The stop token itself is not consumed. An unmatched closing bracket or a hard stop ends the search.
        """
        toks = self.toks
        while True:
            tok = toks[self.pos]
            text = tok.text
            if text in _OPEN:
                self.skip_balanced()
            elif text in stops or text in _CLOSE or tok.kind == EOF or (text in _HARD_STOPS and tok.kind == KW):
                return
            else:
                self.next()

    def skip_past(self, stops: frozenset[str], nested: frozenset[str] = frozenset()) -> None:
        """Consume tokens up to and including the keyword of `stops`, which closes the keyword of `nested`."""
        toks = self.toks
        depth = 0
        idx = self.pos + 1
        while True:
            tok = toks[idx]
            if tok.kind == KW:
                text = tok.text
                if text in _HARD_STOPS:
                    break
                if text in nested:
                    depth += 1
                elif text in stops:
                    if not depth:
                        idx += 1
                        break
                    depth -= 1
            elif tok.kind == EOF:
                break
            idx += 1
        self.skip_to(idx)

    def text(self, start: int, end: int) -> str:
        """Source text of tokens `start` to `end` (exclusive), without comments and directives."""
        if start >= end:
            return ""
        pos = self.toks[start].start
        stop = self.toks[end - 1].end
        gaps = self.gaps
        idx = bisect_left(self._gap_starts, pos)
        parts = []
        while idx < len(gaps) and gaps[idx][0] < stop:
            parts.append(self.source[pos : gaps[idx][0]])
            pos = gaps[idx][1]
            idx += 1
        parts.append(self.source[pos:stop])
        return "".join(parts)


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


def _parse_decl_list(c: Cursor, kind: str) -> list[_Decl]:
    """Parse the parenthesized, comma separated parameter or port declarations of a module header."""
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
            if tok.text in _OPEN:
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


def _parse_body(c: Cursor, mod: _Module) -> None:  # noqa: C901, PLR0912, PLR0915
    """Parse module items up to `endmodule`."""
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
            if text in _DIRECTIONS:
                mod.ports.extend(_parse_item_decl(c))
            elif text in _PARAMS:
                mod.params.extend(_parse_item_decl(c))
            elif text in _PROCEDURES:
                c.next()
                _skip_statement(c)
            elif text in _ASSERTIONS:
                _skip_statement(c)
            elif text in _CONDITIONALS:
                # generate construct: the items within are parsed like any other item
                c.next()
                if c.peek().text == "(":
                    c.skip_balanced()
            elif text in _LABELED:
                c.next()
                _skip_label(c)
            elif text in _BLOCKS:
                c.skip_past(frozenset((_BLOCKS[text],)))
            elif text == "default" and c.peek(1).text in ("clocking", "disable"):
                # default clocking cb; default disable iff (rst);
                c.next()
                if c.peek().text == "disable" or c.peek(2).text == ";":
                    c.skip_until(_SEMI)
            elif text in _DECLARATIONS:
                c.skip_until(_SEMI)
                c.accept(";")
            else:
                c.next()
        elif kind == ID:
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
        elif kind == EOF:
            return
        elif kind == MACRO:
            c.next()
            if c.peek().text == "(":
                c.skip_balanced()
        elif text in _OPEN:
            c.skip_balanced()
        else:
            c.next()


def _parse_module(c: Cursor) -> _Module | None:
    """Parse `module name [imports] [#(parameters)] [(ports)]; items endmodule`."""
    start = c.next()
    while c.peek().text in ("static", "automatic"):
        c.next()
    if c.peek().kind != ID:
        return None
    mod = _Module(start, c.next().text, [], [], [])
    while c.peek().text == "import":
        c.skip_until(_SEMI)
        c.accept(";")
    if c.peek().text == "#" and c.peek(1).text == "(":
        c.next()
        mod.params.extend(_parse_decl_list(c, "parameter"))
    if c.peek().text == "(":
        # names of a non-ANSI port list have neither direction nor type
        mod.ports.extend(decl for decl in _parse_decl_list(c, "") if decl.kind or decl.ptype)
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


def parse(text: str) -> tuple[dm.Module, ...]:
    """Parse SystemVerilog `text` and return its modules."""
    return tuple(
        dm.Module(
            name=mod.name,
            params=_create_params(mod.params, "parameter"),
            localparams=_create_params(mod.params, "localparam"),
            ports=_create_ports(mod.ports),
            insts=_create_insts(mod.insts),
            ifdefs=mod.token.ifdefs,
        )
        for mod in _parse_modules(Cursor(tokenize(text)))
    )
