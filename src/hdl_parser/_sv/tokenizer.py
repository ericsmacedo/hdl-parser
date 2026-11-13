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

"""SystemVerilog Tokenizer.

Splits SystemVerilog source into a flat list of [Token][hdl_parser._sv.tokenizer.Token]s. The tokenizer knows
nothing about the grammar. It only

* classifies identifiers, keywords, numbers, strings, macros and punctuation,
* resolves the `` `ifdef `` nesting, so every token knows the conditions it is compiled under,
* separates comments and compiler directives from the token stream.
"""

import re
from typing import NamedTuple

# Token kinds
ID = "id"
KW = "kw"
NUM = "num"
STR = "str"
MACRO = "macro"
SYS = "sys"
OP = "op"
EOF = "eof"

TYPE_KEYWORDS = frozenset(
    (
        # fmt: off
        "bit",
        "byte",
        "chandle",
        "const",
        "event",
        "int",
        "integer",
        "logic",
        "longint",
        "real",
        "realtime",
        "reg",
        "shortint",
        "shortreal",
        "signed",
        "string",
        "time",
        "type",
        "unsigned",
        "var",
        "void",
        "supply0",
        "supply1",
        "tri",
        "triand",
        "trior",
        "trireg",
        "tri0",
        "tri1",
        "uwire",
        "wand",
        "wire",
        "wor",
        # fmt: on
    )
)

KEYWORDS = frozenset(
    (
        # fmt: off
        "accept_on",
        "alias",
        "always",
        "always_comb",
        "always_ff",
        "always_latch",
        "and",
        "assert",
        "assign",
        "assume",
        "automatic",
        "before",
        "begin",
        "bind",
        "bins",
        "binsof",
        "break",
        "buf",
        "bufif0",
        "bufif1",
        "case",
        "casex",
        "casez",
        "cell",
        "checker",
        "clocking",
        "cmos",
        "config",
        "constraint",
        "context",
        "continue",
        "cover",
        "covergroup",
        "coverpoint",
        "cross",
        "deassign",
        "default",
        "defparam",
        "design",
        "disable",
        "do",
        "edge",
        "else",
        "end",
        "endcase",
        "endchecker",
        "endclocking",
        "endconfig",
        "endfunction",
        "endgenerate",
        "endgroup",
        "endinterface",
        "endmodule",
        "endpackage",
        "endprimitive",
        "endprogram",
        "endproperty",
        "endsequence",
        "endspecify",
        "endtable",
        "endtask",
        "enum",
        "eventually",
        "expect",
        "export",
        "extern",
        "final",
        "first_match",
        "for",
        "force",
        "foreach",
        "forever",
        "fork",
        "forkjoin",
        "function",
        "generate",
        "genvar",
        "global",
        "highz0",
        "highz1",
        "if",
        "iff",
        "ifnone",
        "ignore_bins",
        "illegal_bins",
        "implies",
        "implements",
        "import",
        "incdir",
        "include",
        "initial",
        "inout",
        "input",
        "instance",
        "interconnect",
        "interface",
        "intersect",
        "join",
        "join_any",
        "join_none",
        "large",
        "let",
        "liblist",
        "library",
        "local",
        "localparam",
        "macromodule",
        "matches",
        "medium",
        "modport",
        "module",
        "nand",
        "negedge",
        "nettype",
        "new",
        "nexttime",
        "nmos",
        "nor",
        "noshowcancelled",
        "not",
        "notif0",
        "notif1",
        "null",
        "or",
        "output",
        "package",
        "packed",
        "parameter",
        "pmos",
        "posedge",
        "primitive",
        "priority",
        "program",
        "property",
        "protected",
        "pull0",
        "pull1",
        "pulldown",
        "pullup",
        "pulsestyle_ondetect",
        "pulsestyle_onevent",
        "pure",
        "rand",
        "randc",
        "randcase",
        "randsequence",
        "rcmos",
        "ref",
        "reject_on",
        "release",
        "repeat",
        "restrict",
        "return",
        "rnmos",
        "rpmos",
        "rtran",
        "rtranif0",
        "rtranif1",
        "s_always",
        "s_eventually",
        "s_nexttime",
        "s_until",
        "s_until_with",
        "scalared",
        "sequence",
        "showcancelled",
        "small",
        "soft",
        "solve",
        "specify",
        "specparam",
        "static",
        "strong",
        "strong0",
        "strong1",
        "struct",
        "super",
        "sync_accept_on",
        "sync_reject_on",
        "table",
        "tagged",
        "task",
        "this",
        "throughout",
        "timeprecision",
        "timeunit",
        "tran",
        "tranif0",
        "tranif1",
        "typedef",
        "union",
        "unique",
        "unique0",
        "until",
        "until_with",
        "untyped",
        "use",
        "vectored",
        "virtual",
        "wait",
        "wait_order",
        "weak",
        "weak0",
        "weak1",
        "while",
        "wildcard",
        "with",
        "within",
        "xnor",
        "xor",
        "bit",
        "byte",
        "chandle",
        "const",
        "event",
        "int",
        "integer",
        "logic",
        "longint",
        "real",
        "realtime",
        "reg",
        "shortint",
        "shortreal",
        "signed",
        "string",
        "time",
        "type",
        "unsigned",
        "var",
        "void",
        "supply0",
        "supply1",
        "tri",
        "triand",
        "trior",
        "trireg",
        "tri0",
        "tri1",
        "uwire",
        "wand",
        "wire",
        "wor",
        "class",
        "dist",
        "endclass",
        "extends",
        "inside",
        # fmt: on
    )
)

# Directives which take the rest of the line as argument
_LINE_DIRECTIVES = frozenset(
    ("include", "timescale", "default_nettype", "undef", "line", "pragma", "begin_keywords", "unconnected_drive")
)
# Directives without argument
_PLAIN_DIRECTIVES = frozenset(
    ("resetall", "celldefine", "endcelldefine", "nounconnected_drive", "end_keywords", "undefineall")
)

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
    |(?P<comment>//[^\n]*|/\*.*?\*/)
    |(?P<attr>\(\*(?!\s*\)).*?\*\))
    |(?P<str>"(?:\\.|[^"\\])*")
    |(?P<directive>`[a-zA-Z_]\w*)
    |(?P<id>[a-zA-Z_][\w$]*|\\\S+)
    |(?P<num>'[sS]?[bBoOdDhH]\s*[0-9a-fA-FxXzZ?_]+|\d[\w.]*)
    |(?P<sys>\$[a-zA-Z_][\w$]*)
    |(?P<op>::|[<>=!]=+|<<+|>>+|&&|\|\||->|\+\+|--|.)
    """,
    re.VERBOSE | re.DOTALL,
)
_MACRO_NAME = re.compile(r"\s*([a-zA-Z_]\w*)?")
_DEFINE_BODY = re.compile(r"(?:\\\r?\n|[^\n])*")
_LINE_REST = re.compile(r"[^\n]*")


class Token(NamedTuple):
    """Token.

    Attributes:
        kind: Token kind.
        text: Source text.
        start: Start position within source.
        end: End position within source.
        ifdefs: Conditions, the token is compiled under. Inverted conditions are prefixed with `!`.
    """

    kind: str
    text: str
    start: int
    end: int
    ifdefs: tuple[str, ...]


class Tokens(NamedTuple):
    """Tokenizer Result.

    Attributes:
        source: Source text.
        tokens: Tokens. The last token is always of kind `EOF`.
        comments: Comments, by the index of the token they are located in front of.
        gaps: Source ranges (comments, directives and attributes), which are not covered by tokens.
    """

    source: str
    tokens: list[Token]
    comments: dict[int, list[str]]
    gaps: list[tuple[int, int]]


def _flip(cond: str) -> str:
    return cond[1:] if cond.startswith("!") else f"!{cond}"


def tokenize(source: str) -> Tokens:  # noqa: C901, PLR0912, PLR0915
    """Tokenize SystemVerilog `source`."""
    tokens: list[Token] = []
    comments: dict[int, list[str]] = {}
    gaps: list[tuple[int, int]] = []
    # `ifdef` nesting: active conditions, and number of conditions added per nesting level
    conds: list[str] = []
    levels: list[int] = []
    ifdefs: tuple[str, ...] = ()
    append = tokens.append
    match = _TOKEN.match
    pos = 0
    length = len(source)
    while pos < length:
        mat = match(source, pos)
        kind = mat.lastgroup  # type: ignore[union-attr]
        end = mat.end()  # type: ignore[union-attr]
        if kind == "ws":
            pass
        elif kind == "id":
            text = source[pos:end]
            append(Token(KW if text in KEYWORDS else ID, text, pos, end, ifdefs))
        elif kind == "comment":
            text = source[pos + 2 : end] if source[pos + 1] == "/" else source[pos + 2 : end - 2]
            comments.setdefault(len(tokens), []).append(text.replace("\n", " ").strip())
            gaps.append((pos, end))
        elif kind == "directive":
            name = source[pos + 1 : end]
            if name in ("ifdef", "ifndef", "elsif"):
                mat = _MACRO_NAME.match(source, end)
                end = mat.end()  # type: ignore[union-attr]
                cond = mat.group(1) or ""  # type: ignore[union-attr]
                if name == "elsif":
                    if levels:
                        conds[-1] = _flip(conds[-1])
                        conds.append(cond)
                        levels[-1] += 1
                else:
                    conds.append(cond if name == "ifdef" else _flip(cond))
                    levels.append(1)
                ifdefs = tuple(conds)
            elif name == "else":
                if levels:
                    conds[-1] = _flip(conds[-1])
                    ifdefs = tuple(conds)
            elif name == "endif":
                if levels:
                    del conds[-levels.pop() :]
                    ifdefs = tuple(conds)
            elif name == "define":
                end = _DEFINE_BODY.match(source, end).end()  # type: ignore[union-attr]
            elif name in _LINE_DIRECTIVES:
                end = _LINE_REST.match(source, end).end()  # type: ignore[union-attr]
            elif name not in _PLAIN_DIRECTIVES:
                append(Token(MACRO, source[pos:end], pos, end, ifdefs))
                pos = end
                continue
            gaps.append((pos, end))
        elif kind == "attr":
            gaps.append((pos, end))
        else:
            append(Token(kind, source[pos:end], pos, end, ifdefs))  # type: ignore[arg-type]
        pos = end
    append(Token(EOF, "", length, length, ifdefs))
    return Tokens(source=source, tokens=tokens, comments=comments, gaps=gaps)
