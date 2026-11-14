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

This is no full preprocessor. It does just enough to make code created by macros (ports, parameters,
instances, ...) visible to the parser:

* `` `define `` collection (object-like and function-like, default arguments, line continuation)
* expansion of known macros, everywhere except in comments and strings
* argument substitution, token pasting (` `` `), stringification (`` `" ``) and nested macros
* `` `include "file" `` is followed to collect the `` `define `` statements of the included file.
  The included code itself is **not** inserted.

Not supported by intention:

* evaluation of `` `ifdef `` - a macro with conflicting definitions is never expanded
* `` `undef ``
"""

import logging
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_MAX_DEPTH = 32
"""Maximum macro nesting depth."""

_RE_SCAN = re.compile(
    r"""
      (?P<comment>//[^\n]*|/\*.*?\*/)
    | (?P<string>"(?:\\.|[^"\\\n])*")
    | `include[ \t]*"(?P<include>[^"\n]*)"
    | `define[ \t]+(?P<dname>[a-zA-Z_]\w*)(?P<dbody>(?:\\\r?\n|[^\n])*)
    | `(?P<macro>[a-zA-Z_]\w*)
    """,
    re.DOTALL | re.VERBOSE,
)
_RE_STRING = r'"(?:\\.|[^"\\\n])*"'
# comment within macro body. strings are matched too, to skip them.
_RE_BODY_COMMENT = re.compile(rf"{_RE_STRING}|(?P<comment>//[^\n]*?)(?=\\?\r?\n|\Z)")
_RE_CONTINUATION = re.compile(r"\\(\r?\n)")
# identifier within macro body - but not macro names (preceded by a single backtick). strings are skipped.
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


class _Defines:
    """Collects `` `define `` macros from text and all included files."""

    def __init__(self, inc_dirs: Iterable[Path] = ()):
        self.macros: dict[str, Macro] = {}
        self.ambiguous: set[str] = set()
        self.inc_dirs = tuple(inc_dirs)
        self.files: set[Path] = set()

    def read(self, file_path: Path) -> str | None:
        """Read `file_path` and collect its macros. `None` if the file has been read already."""
        resolved = file_path.resolve()
        if resolved in self.files:
            return None
        self.files.add(resolved)
        text = file_path.read_text()
        self.collect(text, str(file_path), file_path.parent)
        return text

    def collect(self, text: str, context: str, basedir: Path | None = None) -> None:
        """Collect macros from `text`. Files included relative to `basedir` or `inc_dirs` are read too."""
        if "`define" not in text and "`include" not in text:
            return
        for mat in _RE_SCAN.finditer(text):
            kind = mat.lastgroup
            if kind == "dbody":
                self._define(mat.group("dname"), mat.group("dbody"), context)
            elif kind == "include":
                self._include(mat.group("include"), context, basedir)

    def _define(self, name: str, text: str, context: str) -> None:
        if name in self.ambiguous:
            return
        macro = _parse_define(name, text)
        if macro is None:
            LOGGER.warning("%s: cannot parse definition of macro `%s. Skipped.", context, name)
        elif self.macros.setdefault(name, macro) != macro:
            LOGGER.debug("%s: macro `%s has conflicting definitions.", context, name)
            self.ambiguous.add(name)
            del self.macros[name]

    def _include(self, name: str, context: str, basedir: Path | None) -> None:
        dirs = self.inc_dirs if basedir is None else (basedir, *self.inc_dirs)
        for directory in dirs:
            file_path = directory / name
            if file_path.is_file():
                try:
                    self.read(file_path)
                except (OSError, UnicodeError) as exc:
                    LOGGER.warning("%s: cannot read included file '%s': %s", context, file_path, exc)
                return
        LOGGER.info("%s: included file '%s' not found. Its macros are unknown.", context, name)


def collect_defines(
    texts: Iterable[str] = (), file_paths: Iterable[Path] = (), inc_dirs: Iterable[Path] = ()
) -> dict[str, Macro]:
    """Collect all `` `define `` macros from `texts` and `file_paths`.

    Included files are searched next to the including file and in `inc_dirs`.
    Conditionals (`` `ifdef ``) are **not** evaluated.
    A macro which is defined multiple times with different content is ambiguous and therefore skipped.
    """
    defines = _Defines(inc_dirs)
    for text in texts:
        defines.collect(text, "<text>")
    for file_path in file_paths:
        defines.read(file_path)
    for name in sorted(defines.ambiguous):
        LOGGER.warning("macro `%s has conflicting definitions. Skipped.", name)
    return defines.macros


def expand(
    text: str, macros: Macros | None = None, file_path: Path | None = None, inc_dirs: Iterable[Path] = ()
) -> str:
    """Expand macros.

    Macros are taken from `macros`, from the `` `define `` statements within `text` and from the files
    included by `text`. Included files are searched next to `file_path` and in `inc_dirs`.
    `macros` take precedence. Unknown macros are left untouched.
    """
    if "`" not in text:
        return text
    context = str(file_path) if file_path else "<text>"
    defines = _Defines(inc_dirs)
    if file_path:
        defines.files.add(file_path.resolve())
    defines.collect(text, context, file_path.parent if file_path else None)
    all_macros = {**defines.macros, **(macros or {})}
    ambiguous = defines.ambiguous.difference(all_macros)
    if not all_macros and not ambiguous:
        return text
    out: list[str] = []
    _Expander(all_macros, ambiguous, context, out).scan(text)
    return "".join(out)


class _Expander:
    """Copies text to `out` and expands macros."""

    def __init__(self, macros: Macros, ambiguous: set[str], context: str, out: list[str]):
        self.macros = macros
        self.ambiguous = ambiguous
        self.context = context
        self.out = out
        self.active: list[str] = []

    def scan(self, text: str) -> None:
        pos = 0
        for mat in _RE_SCAN.finditer(text):
            if mat.lastgroup != "macro" or mat.start() < pos:
                # no macro, or part of a macro call which has been replaced
                continue
            result = self._expand_call(text, mat)
            if result is not None:
                expanded, end = result
                self.out.append(text[pos : mat.start()])
                pos = end
                # the expanded text is scanned again, to expand nested macros
                self.active.append(mat.group("macro"))
                self.scan(expanded)
                self.active.pop()
        self.out.append(text[pos:])

    def _expand_call(self, text: str, mat: re.Match) -> tuple[str, int] | None:
        """Expand macro call at `mat`. Return expanded text and end position of the call within `text`."""
        name = mat.group("macro")
        macro = self.macros.get(name)
        if macro is None:
            if name in self.ambiguous:
                # report once
                self.ambiguous.remove(name)
                LOGGER.warning("%s: macro `%s has conflicting definitions. Not expanded.", self.context, name)
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
