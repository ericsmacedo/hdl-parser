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

"""Tokens And Cursor.

Language independent part of the parsers: the tokenizers create [Tokens][hdl_parser._tokens.Tokens] and the
parsers read them through a [Cursor][hdl_parser._tokens.Cursor].
"""

from bisect import bisect_left
from typing import NamedTuple

# Token kinds
ID = "id"
KW = "kw"
NUM = "num"
STR = "str"
OP = "op"
EOF = "eof"

OPEN = frozenset("([{")
CLOSE = frozenset(")]}")


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


class Cursor:
    """Position Within The Token Stream.

    Comments are not part of the token stream. They are handed over to `sink` (if set), as soon as the token
    behind them is consumed. A declaration sets `sink` to its own comment list, to receive all comments up to
    the next declaration.

    Nothing is ever skipped beyond the end of the token stream or a keyword of `hard_stops`.
    """

    __slots__ = ("_gap_starts", "comments", "gaps", "hard_stops", "last", "pos", "sink", "source", "toks")

    def __init__(self, tokens: Tokens, hard_stops: frozenset[str] = frozenset()):
        self.hard_stops = hard_stops
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
        hard_stops = self.hard_stops
        depth = 0
        while True:
            tok = toks[idx]
            text = tok.text
            if text in OPEN:
                depth += 1
            elif text in CLOSE:
                depth -= 1
                if depth <= 0:
                    return idx + 1
            elif tok.kind == EOF or (text in hard_stops and tok.kind == KW):
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
        hard_stops = self.hard_stops
        while True:
            tok = toks[self.pos]
            text = tok.text
            if text in OPEN:
                self.skip_balanced()
            elif text in stops or text in CLOSE or tok.kind == EOF or (text in hard_stops and tok.kind == KW):
                return
            else:
                self.next()

    def skip_past(self, stops: frozenset[str], nested: frozenset[str] = frozenset()) -> None:
        """Consume tokens up to and including the keyword of `stops`, which closes the keyword of `nested`."""
        toks = self.toks
        hard_stops = self.hard_stops
        depth = 0
        idx = self.pos + 1
        while True:
            tok = toks[idx]
            if tok.kind == KW:
                text = tok.text
                if text in hard_stops:
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
