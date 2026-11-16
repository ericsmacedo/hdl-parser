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

"""Signal References Of Expressions.

[reads][hdl_parser._refs.reads] tells the names an expression reads, [targets][hdl_parser._refs.targets] the
names the target of an assignment (the left hand side) writes.

Both work on tokens. A name is any identifier, which is no

* member of a struct, record or interface (`bus.req` reads `bus`),
* package or item of a package (`pkg::WIDTH`),
* called function (`f(a)` reads `a`, SystemVerilog only: VHDL calls look like indices),
* type of a cast (`logic'(a)`, `WIDTH'(a)`),
* attribute (VHDL: `clk'event`),
* field name of an assignment pattern or aggregate (`'{valid: a}`, `(valid => a)`).

Parameters and other constants are names too. They are left out by the caller, which knows them.
"""

from collections.abc import Iterable, Sequence
from typing import NamedTuple

from ._sv.tokenizer import tokenize as tokenize_sv
from ._tokens import CLOSE, ID, OPEN, Token
from ._vhdl.tokenizer import tokenize as tokenize_vhdl


class Target(NamedTuple):
    """One Name Written By The Target Of An Assignment.

    Attributes:
        name: Name.
        select: Select, as written: `[3:0]`, `.field`. Empty for the whole name.
        reads: Names read by the select: `idx` of `mem[idx]`.
    """

    name: str
    select: str
    reads: tuple[str, ...]


def unique(names: Iterable[str]) -> tuple[str, ...]:
    """`names` without duplicates, in their order."""
    return tuple(dict.fromkeys(names))


def reads(toks: Sequence[Token], lang: str = "sv", paths: bool = False) -> tuple[str, ...]:
    """Names read by the expression `toks`, in their order, without duplicates.

    `paths`: SystemVerilog: a hierarchical reference is returned as written, with its indices: `g[0].data`, `bus.req`.
    """
    return unique(_vhdl_reads(toks) if lang == "vhdl" else _sv_reads(toks, paths))


def split_reads(
    toks: Sequence[Token], lang: str = "sv", paths: bool = False
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Names read by the expression `toks`: the data, and the ones read by conditions only (`sel ? a : b`).

    VHDL expressions have no conditions: their conditions belong to the statement.
    """
    if lang == "vhdl":
        return reads(toks, lang), ()
    marked = _conditions(toks)
    if not marked:
        return reads(toks, lang, paths), ()
    data = unique(_sv_reads(toks, paths, only=set(range(len(toks))) - marked))
    conds = _sv_reads(toks, paths, only=marked)
    return data, unique(name for name in conds if name not in data)


def _conditions(toks: Sequence[Token]) -> set[int]:
    """Indices of the tokens, which are the condition of a conditional operator `cond ? a : b`."""
    marked: set[int] = set()
    # start of the current operand, per bracket depth
    starts = [0]
    for idx, tok in enumerate(toks):
        text = tok.text
        if text in OPEN:
            starts.append(idx + 1)
        elif text in CLOSE:
            if len(starts) > 1:
                starts.pop()
        elif text in (",", ":", ";"):
            starts[-1] = idx + 1
        elif text == "?":
            marked.update(range(starts[-1], idx))
            starts[-1] = idx + 1
    return marked


def base(name: str) -> str:
    """Name of the reference `name` without members and indices: `g` of `g[0].data`."""
    end = len(name)
    for char in ".[":
        pos = name.find(char)
        if pos != -1:
            end = min(end, pos)
    return name[:end]


def _sv_reads(toks: Sequence[Token], paths: bool = False, only: set[int] | None = None) -> Iterable[str]:
    # groups opened in front of the current token: is it an assignment pattern `'{...}`?
    patterns: list[bool] = []
    last = len(toks) - 1
    for idx, tok in enumerate(toks):
        text = tok.text
        if text in OPEN:
            patterns.append(text == "{" and idx > 0 and toks[idx - 1].text == "'")
            continue
        if text in CLOSE:
            if patterns:
                patterns.pop()
            continue
        if tok.kind != ID:
            continue
        prev = toks[idx - 1].text if idx else ""
        nxt = toks[idx + 1].text if idx < last else ""
        if prev in (".", "::") or nxt in ("::", "'", "("):
            continue
        if nxt == ":" and patterns and patterns[-1]:
            # field name of an assignment pattern
            continue
        if only is not None and idx not in only:
            continue
        yield _path(toks, idx) if paths else text


def _path(toks: Sequence[Token], idx: int) -> str:
    """The hierarchical reference starting at `idx`: `g[0].data`. Just the name, if it is none."""
    end = idx + 1
    pos = end
    while pos < len(toks):
        while pos < len(toks) and toks[pos].text == "[":
            pos = _group_end(toks, pos)
        if pos + 1 < len(toks) and toks[pos].text == "." and toks[pos + 1].kind == ID:
            pos += 2
            end = pos
        else:
            break
    return join(toks[idx:end])


def _vhdl_reads(toks: Sequence[Token]) -> Iterable[str]:
    last = len(toks) - 1
    for idx, tok in enumerate(toks):
        if tok.kind != ID:
            continue
        prev = toks[idx - 1].text if idx else ""
        nxt = toks[idx + 1].text if idx < last else ""
        if prev in (".", "'") or nxt == "=>":
            continue
        yield tok.text


def targets(toks: Sequence[Token], lang: str = "sv") -> list[Target]:
    """Names written by the assignment target `toks`. A concatenation (VHDL: aggregate) is split."""
    if not toks:
        return []
    opening = "(" if lang == "vhdl" else "{"
    if toks[0].text == opening and _group_end(toks, 0) == len(toks):
        result: list[Target] = []
        for part in _split(toks[1:-1]):
            result += targets(part, lang)
        return result
    if toks[0].kind != ID:
        return []
    select = toks[1:]
    return [Target(toks[0].text, join(select), reads(select, lang))]


def _group_end(toks: Sequence[Token], idx: int) -> int:
    """Index behind the bracket group starting at `idx`."""
    depth = 0
    for pos in range(idx, len(toks)):
        text = toks[pos].text
        if text in OPEN:
            depth += 1
        elif text in CLOSE:
            depth -= 1
            if depth <= 0:
                return pos + 1
    return len(toks)


def _split(toks: Sequence[Token]) -> list[Sequence[Token]]:
    """Split `toks` at the commas, which are not located within brackets."""
    parts: list[Sequence[Token]] = []
    depth = 0
    start = 0
    for pos, tok in enumerate(toks):
        if tok.text in OPEN:
            depth += 1
        elif tok.text in CLOSE:
            depth -= 1
        elif tok.text == "," and depth == 0:
            parts.append(toks[start:pos])
            start = pos + 1
    parts.append(toks[start:])
    return [part for part in parts if part]


def join(toks: Sequence[Token]) -> str:
    """Text of `toks` on one line: words are separated by a space, nothing else is."""
    parts: list[str] = []
    prev = ""
    for tok in toks:
        text = tok.text
        if prev and _word(prev[-1]) and _word(text[0]):
            parts.append(" ")
        parts.append(text)
        prev = text
    return "".join(parts)


def _word(char: str) -> bool:
    return char.isalnum() or char in "_$'\\"


def tokens(text: str, lang: str = "sv") -> list[Token]:
    """Tokens of `text`, without the end token."""
    return (tokenize_vhdl(text) if lang == "vhdl" else tokenize_sv(text)).tokens[:-1]


def reads_text(text: str, lang: str = "sv", paths: bool = False) -> tuple[str, ...]:
    """Names read by the expression `text`."""
    return reads(tokens(text, lang), lang, paths)


def targets_text(text: str, lang: str = "sv") -> list[Target]:
    """Names written by the assignment target `text`."""
    return targets(tokens(text, lang), lang)
