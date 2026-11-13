# MIT License
#
# Copyright (c) 2026 ericsmacedo
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

"""Lightweight SystemVerilog Macro Expander.

This is no full preprocessor. It does just enough to make macros which define ports or parameters
in a module header visible to the parser:

* `` `define `` collection (object-like and function-like, default arguments, line continuation)
* expansion of known macros **within module headers only**
* argument substitution, token pasting (` `` `), stringification (`` `" ``) and nested macros

Not supported by intention:

* `` `include `` - provide the macro files explicitly instead
* evaluation of `` `ifdef `` - a macro with conflicting definitions is never expanded
* `` `undef ``
"""

import logging
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

LOGGER = logging.getLogger(__name__)

_MAX_DEPTH = 32
"""Maximum macro nesting depth."""

_RE_SCAN = re.compile(
    r"""
      (?P<comment>//[^\n]*|/\*.*?\*/)
    | (?P<string>"(?:\\.|[^"\\\n])*")
    | `define[ \t]+(?P<dname>[a-zA-Z_]\w*)(?P<dbody>(?:\\\r?\n|[^\n])*)
    | `(?P<macro>[a-zA-Z_]\w*)
    | (?P<kw>\b(?:macromodule|module|import)\b)
    | (?P<punct>[();])
    """,
    re.DOTALL | re.VERBOSE,
)
_RE_STRING = r'"(?:\\.|[^"\\\n])*"'
# comment within macro body. strings are matched too, to skip them.
_RE_BODY_COMMENT = re.compile(rf"{_RE_STRING}|(?P<comment>//[^\n]*?)(?=\\?\r?\n|\Z)")
_RE_CONTINUATION = re.compile(r"\\(\r?\n)")
# identifier within macro body - but not macro names (leaded by a single backtick). strings are skipped.
_RE_BODY_IDENT = re.compile(rf"{_RE_STRING}|(?<!(?<!`)`)\b(?P<ident>[a-zA-Z_]\w*)\b")
_RE_IDENT = re.compile(r"[a-zA-Z_]\w*\Z")
_OPEN = "([{"
_CLOSE = ")]}"


@dataclass(frozen=True)
class Macro:
    """A `` `define `` Macro.

    Attributes:
        name: Macro name, without backtick.
        body: Replacement text.
        params: Formal arguments as pairs of name and default (`None` for no default).
                `None` for object-like macros (macros without arguments).
    """

    name: str
    body: str
    params: tuple[tuple[str, str | None], ...] | None = None


Macros = Mapping[str, Macro]
"""Macros by name."""


def collect_defines(text: str, context: str = "") -> dict[str, Macro]:
    """Collect all `` `define `` macros from `text`.

    Conditionals (`` `ifdef ``) are **not** evaluated.
    A macro which is defined multiple times with different content is ambiguous and therefore skipped.
    """
    macros: dict[str, Macro] = {}
    if "`define" not in text:
        return macros
    ambiguous = set()
    for mat in _RE_SCAN.finditer(text):
        name = mat.group("dname")
        if not name or name in ambiguous:
            continue
        macro = _parse_define(name, mat.group("dbody"))
        if macro is None:
            LOGGER.warning("%s: cannot parse definition of macro `%s. Skipped.", context or "<text>", name)
        elif macros.setdefault(name, macro) != macro:
            LOGGER.warning("%s: macro `%s has conflicting definitions. Skipped.", context or "<text>", name)
            ambiguous.add(name)
            del macros[name]
    return macros


def expand(text: str, macros: Macros | None = None, context: str = "") -> str:
    """Expand macros within module headers.

    Macros are taken from `macros` and from the `` `define `` statements within `text`.
    `macros` take precedence. Unknown macros are left untouched.
    """
    if "`" not in text:
        return text
    all_macros = {**collect_defines(text, context=context), **(macros or {})}
    if not all_macros:
        return text
    out: list[str] = []
    _Expander(all_macros, context or "<text>", out).scan(text)
    return "".join(out)


class _Expander:
    """Copies text to `out` and expands macros on module headers."""

    def __init__(self, macros: Macros, context: str, out: list[str]):
        self.macros = macros
        self.context = context
        self.out = out
        self.in_header = False
        self.paren_level = 0
        self.in_import = False
        self.active: list[str] = []

    def scan(self, text: str) -> None:
        pos = 0
        for mat in _RE_SCAN.finditer(text):
            if mat.start() < pos:
                continue  # part of macro call, which has been replaced
            kind = mat.lastgroup
            if kind == "kw":
                self._handle_keyword(mat.group())
            elif kind == "punct":
                self._handle_punct(mat.group())
            elif kind == "macro" and self.in_header:
                result = self._expand_call(text, mat)
                if result is not None:
                    expanded, end = result
                    self.out.append(text[pos : mat.start()])
                    pos = end
                    # the expanded text is scanned again: nested macros, and the header may end within the macro.
                    self.active.append(mat.group("macro"))
                    self.scan(expanded)
                    self.active.pop()
        self.out.append(text[pos:])

    def _handle_keyword(self, keyword: str) -> None:
        if keyword == "import":
            # 'module name import pkg::*; (' - this semicolon does not end the header
            self.in_import = self.in_header and not self.paren_level
        else:
            self.in_header = True
            self.paren_level = 0
            self.in_import = False

    def _handle_punct(self, punct: str) -> None:
        if not self.in_header:
            return
        if punct == "(":
            self.paren_level += 1
        elif punct == ")":
            self.paren_level -= 1
        elif self.paren_level <= 0:
            if self.in_import:
                self.in_import = False
            else:
                self.in_header = False

    def _expand_call(self, text: str, mat: re.Match) -> tuple[str, int] | None:
        """Expand macro call at `mat`. Return expanded text and end position of the call within `text`."""
        name = mat.group("macro")
        macro = self.macros.get(name)
        if macro is None:
            return None
        if name in self.active or len(self.active) >= _MAX_DEPTH:
            LOGGER.warning("%s: recursive macro `%s is not expanded.", self.context, name)
            return None
        if macro.params is None:
            return macro.body, mat.end()
        # function-like macro
        start = _skip_spaces(text, mat.end())
        end = find_closing(text, start)
        if end is None:
            LOGGER.warning("%s: macro `%s requires arguments. Not expanded.", self.context, name)
            return None
        args = _bind_args(macro, split_args(text[start + 1 : end - 1]))
        if args is None:
            LOGGER.warning("%s: macro `%s is used with wrong number of arguments. Not expanded.", self.context, name)
            return None
        return _substitute(macro.body, args), end


def _parse_define(name: str, text: str) -> Macro | None:
    """Create macro `name` from the remainder of the `` `define `` statement."""
    params: tuple[tuple[str, str | None], ...] | None = None
    # A function-like macro has its '(' right behind the name
    if text.startswith("("):
        end = find_closing(text, 0)
        if end is None:
            return None
        params = tuple(_parse_params(text[1 : end - 1]))
        if not all(_RE_IDENT.match(pname) for pname, _ in params):
            return None
        text = text[end:]
    body = _RE_BODY_COMMENT.sub(lambda mat: "" if mat.group("comment") else mat.group(), text)
    body = _RE_CONTINUATION.sub(r"\1", body).strip()
    return Macro(name=name, body=body, params=params)


def _parse_params(text: str) -> Iterator[tuple[str, str | None]]:
    for param in split_args(text):
        pname, sep, default = param.partition("=")
        yield pname.strip(), (default.strip() if sep else None)


def _skip_spaces(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _iter_toplevel(text: str, pos: int = 0) -> Iterator[tuple[int, str, int]]:
    """Iterate over `text` and yield `(pos, char, level)` for everything outside of strings."""
    level = 0
    end = len(text)
    while pos < end:
        char = text[pos]
        if char == '"':
            pos += 1
            while pos < end and text[pos] != '"':
                pos += 2 if text[pos] == "\\" else 1
        elif char in _OPEN:
            level += 1
            yield pos, char, level
        elif char in _CLOSE:
            level -= 1
            yield pos, char, level
        else:
            yield pos, char, level
        pos += 1


def find_closing(text: str, pos: int) -> int | None:
    """Return position behind the parenthesis closing the one at `pos`."""
    if not text.startswith("(", pos):
        return None
    for idx, _, level in _iter_toplevel(text, pos):
        if level == 0:
            return idx + 1
    return None


def split_args(text: str) -> list[str]:
    """Split at top-level commas."""
    if not text.strip():
        return []
    args = []
    start = 0
    for idx, char, level in _iter_toplevel(text):
        if char == "," and level == 0:
            args.append(text[start:idx].strip())
            start = idx + 1
    args.append(text[start:].strip())
    return args


def _bind_args(macro: Macro, args: list[str]) -> dict[str, str] | None:
    """Assign actual arguments to formal arguments."""
    params = macro.params or ()
    if len(args) > len(params):
        return None
    bound = {}
    for idx, (pname, default) in enumerate(params):
        if idx < len(args) and args[idx]:
            bound[pname] = args[idx]
        elif default is not None:
            bound[pname] = default
        elif idx < len(args) or len(params) == 1:
            # explicit empty argument. `FOO() is legal on macros with one argument
            bound[pname] = ""
        else:
            return None
    return bound


def _substitute(body: str, args: dict[str, str]) -> str:
    """Replace formal arguments in `body`, paste tokens and resolve stringification."""

    def repl(mat: re.Match) -> str:
        ident = mat.group("ident")
        if ident is None:
            return mat.group()
        return args.get(ident, ident)

    # within `"...`" arguments are replaced too, so resolve it first.
    body = body.replace('`\\`"', "\x00").replace('`"', "\x01")
    body = _RE_BODY_IDENT.sub(repl, body)
    return body.replace("``", "").replace("\x00", '\\"').replace("\x01", '"')
