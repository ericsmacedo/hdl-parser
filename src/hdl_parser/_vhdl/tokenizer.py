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

"""VHDL Tokenizer.

Splits VHDL source into a flat list of [Token][hdl_parser._tokens.Token]s. The tokenizer knows nothing about
the grammar. It only

* classifies identifiers, keywords, numbers, strings and punctuation,
* separates comments from the token stream.

VHDL is case insensitive. The text of keyword tokens is always lower case, everything else is kept as written.
"""

import re

from .._tokens import EOF, ID, KW, OP, STR, Token, Tokens  # noqa: TID252

# fmt: off
KEYWORDS = frozenset(
    (
        "abs", "access", "after", "alias", "all", "and", "architecture", "array", "assert", "assume",
        "assume_guarantee", "attribute", "begin", "block", "body", "buffer", "bus", "case", "component",
        "configuration", "constant", "context", "cover", "default", "disconnect", "downto", "else", "elsif", "end",
        "entity", "exit", "fairness", "file", "for", "force", "function", "generate", "generic", "group", "guarded",
        "if", "impure", "in", "inertial", "inout", "is", "label", "library", "linkage", "literal", "loop", "map",
        "mod", "nand", "new", "next", "nor", "not", "null", "of", "on", "open", "or", "others", "out", "package",
        "parameter", "port", "postponed", "procedure", "process", "property", "protected", "pure", "range",
        "record", "register", "reject", "release", "rem", "report", "restrict", "restrict_guarantee", "return",
        "rol", "ror", "select", "sequence", "severity", "shared", "signal", "sla", "sll", "sra", "srl", "strong",
        "subtype", "then", "to", "transport", "type", "unaffected", "units", "until", "use", "variable", "vmode",
        "vprop", "vunit", "wait", "when", "while", "with", "xnor", "xor",
    )
)
# fmt: on

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
    |(?P<comment>--[^\n]*|/\*.*?\*/)
    |(?P<num>\d*[sSuU]?[bBoOxXdD]"[^"\n]*"|\d(?:\w|\.(?=\d)|\#)*)
    |(?P<str>"(?:[^"\n]|"")*")
    |(?P<id>[a-zA-Z]\w*|\\(?:[^\\\n]|\\\\)+\\)
    |(?P<char>'[^\n]')
    |(?P<op>:=|=>|<=|>=|/=|\*\*|<>|<<|>>|\?\?|\?/=|\?[<>]?=|\?[<>]|.)
    """,
    re.VERBOSE | re.DOTALL,
)
# A tick behind one of these is an attribute or a qualified expression, and not the start of a character literal.
_NAME_ENDS = frozenset((")", "]", "all"))


def tokenize(source: str) -> Tokens:
    """Tokenize VHDL `source`."""
    tokens: list[Token] = []
    comments: dict[int, list[str]] = {}
    gaps: list[tuple[int, int]] = []
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
            lower = text.lower()
            if lower in KEYWORDS:
                append(Token(KW, lower, pos, end, ()))
            else:
                append(Token(ID, text, pos, end, ()))
        elif kind == "comment":
            comments.setdefault(len(tokens), []).append(source[pos:end].replace("\n", " ").strip())
            gaps.append((pos, end))
        elif kind == "char":
            if tokens and (tokens[-1].kind == ID or tokens[-1].text in _NAME_ENDS):
                end = pos + 1
                append(Token(OP, "'", pos, end, ()))
            else:
                append(Token(STR, source[pos:end], pos, end, ()))
        else:
            append(Token(kind, source[pos:end], pos, end, ()))  # type: ignore[arg-type]
        pos = end
    append(Token(EOF, "", length, length, ()))
    return Tokens(source=source, tokens=tokens, comments=comments, gaps=gaps)
