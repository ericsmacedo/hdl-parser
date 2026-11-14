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

"""Lightweight SystemVerilog Preprocessor.

This is no full preprocessor. It does just enough to make code created by macros (ports, parameters,
instances, ...) visible to the parser.

The text is processed **once, from top to bottom**. On the way

* `` `define `` and `` `undef `` update the table of known macros
  (object-like and function-like, default arguments, line continuation),
* `` `include "file" `` processes the included file at this point, to learn its macros.
  The included code itself is **not** inserted,
* known macros are replaced, everywhere except in comments and strings. This includes argument substitution,
  token pasting (` `` `), stringification (`` `" ``) and nested macros. The replacement is processed
  like any other text, so directives created by macros just work,
* `` `ifdef `` conditions are resolved on request - but only the ones which are safe to resolve.

Conditions:

A macro we have seen the definition of **is** defined. A macro we have not seen the definition of is not
necessarily undefined. It may be defined on the command line of the simulator, by the tool itself or by a file
which has been compiled earlier. So a condition is

* *true* (`` `ifdef X ``) or *false* (`` `ifndef X ``), if `X` is known to be defined: the code which is not
  compiled is removed, including its `` `define `` statements. The directives are removed too.
* *unknown* in any other case: everything is kept, the tokenizer tags the code with its condition. A macro
  defined here is *conditional*: it is expanded, as long as there is no other definition with a different
  body, but it is not known to be defined.

Include guards and defaults (`` `ifndef X `` directly followed by `` `define X ``) are assumed to be compiled.
"""

import logging
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_MAX_DEPTH = 32
"""Maximum macro nesting depth."""

_RE_SCAN = re.compile(
    r"""
      (?P<comment>//[^\n]*|/\*.*?\*/)
    | (?P<string>"(?:\\.|[^"\\\n])*")
    | `include[ \t]*"(?P<include>[^"\n]*)"
    | `define[ \t]+(?P<dname>[a-zA-Z_]\w*)(?P<define>(?:\\\r?\n|[^\n])*)
    | `undef[ \t]+(?P<undef>[a-zA-Z_]\w*)
    | `(?P<cond>ifdef|ifndef|elsif)\b(?:\s*(?P<cname>[a-zA-Z_]\w*))?
    | `(?P<condend>else|endif)\b
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
# `define behind `ifndef: include guard or default value
_RE_GUARD = re.compile(r"(?:\s|//[^\n]*|/\*.*?\*/)*`define[ \t]+([a-zA-Z_]\w*)", re.DOTALL)
_OPEN = "([{"
_CLOSE = ")]}"

# Code is ...
_ACTIVE = 0  # ... compiled
_UNCERTAIN = 1  # ... compiled or not, it depends on an unknown condition
_INACTIVE = 2  # ... not compiled


@dataclass(frozen=True)
class Macro:
    """A `` `define `` Macro.

    Attributes:
        name: Macro name, without backtick.
        body: Replacement text.
        params: Formal arguments as pairs of name and default (`None` for no default).
                `None` for object-like macros (macros without arguments).
        conditional: The macro is defined under an unknown `` `ifdef `` condition.
                     It is expanded, but never used to resolve `` `ifdef `` conditions.
    """

    name: str
    body: str
    params: tuple[tuple[str, str | None], ...] | None = None
    conditional: bool = field(default=False, compare=False)


Macros = Mapping[str, Macro]
"""Macros by name."""


@dataclass
class _Cond:
    """One `` `ifdef `` ... `` `endif ``."""

    parent: int
    """State of the code around."""
    taken: bool = False
    """One branch is known to be compiled. All following ones are not."""
    unknown: bool = False
    """One of the branches so far has an unknown condition."""
    opened: bool = False
    """One of the directives so far has been kept."""


class _Preprocessor:
    """Processes text from top to bottom.

    Attributes:
        macros: Known macros, at the current position.
        ambiguous: Macros with different definitions under unknown conditions. They are not expanded.
    """

    def __init__(self, macros: Macros | None = None, inc_dirs: Iterable[Path] = (), resolve_ifdefs: bool = False):
        self.macros: dict[str, Macro] = dict(macros or {})
        self.ambiguous: set[str] = set()
        # macros handed over are never touched
        self.fixed = frozenset(self.macros)
        self.inc_dirs = tuple(inc_dirs)
        self.resolve_ifdefs = resolve_ifdefs
        self.state = _ACTIVE
        self.conds: list[_Cond] = []
        # macros which are just expanded, files which are just included, files which are done
        self.expanding: list[str] = []
        self.including: list[Path] = []
        self.included: set[Path] = set()

    def process_file(self, file_path: Path, out: list[str] | None = None) -> None:
        """Process the file at `file_path`."""
        text = file_path.read_text()
        self.including.append(file_path.resolve())
        self.process(text, str(file_path), file_path.parent, out)
        self.including.pop()

    def process(self, text: str, context: str, basedir: Path | None = None, out: list[str] | None = None) -> None:  # noqa: C901, PLR0912
        """Process `text` and append the result to `out`.

        Files are included relative to `basedir` and the include directories.
        """
        pos = 0
        for mat in _RE_SCAN.finditer(text):
            kind = mat.lastgroup
            start = mat.start()
            if kind in ("comment", "string") or start < pos:
                # nothing to do, or part of a macro call which has been replaced
                continue
            if kind in ("cond", "cname", "condend"):
                # the state changes: flush
                if out is not None and self.state != _INACTIVE:
                    out.append(text[pos:start])
                pos = mat.end()
                if kind == "condend":
                    directive = self._branch_end(mat.group("condend"), mat.group())
                else:
                    directive = self._branch(mat.group("cond"), mat.group("cname"), mat.group(), text, pos)
                if out is not None:
                    out.append(directive)
            elif self.state == _INACTIVE:
                pass
            elif kind == "macro":
                result = self._expand_call(text, mat, context)
                if result is not None:
                    expanded, end = result
                    if out is not None:
                        out.append(text[pos:start])
                    pos = end
                    # the replacement is processed like any other text
                    self.expanding.append(mat.group("macro"))
                    self.process(expanded, context, basedir, out)
                    self.expanding.pop()
            elif kind == "define":
                self._define(mat.group("dname"), mat.group("define"), context)
            elif kind == "undef":
                self._undef(mat.group("undef"))
            else:
                self._include(mat.group("include"), context, basedir)
        if out is not None and self.state != _INACTIVE:
            out.append(text[pos:])

    # --- conditions ---

    def reset_conds(self) -> None:
        """Forget all open conditions."""
        self.conds.clear()
        self.state = _ACTIVE

    def _is_defined(self, name: str | None) -> bool:
        """`name` is known to be defined."""
        if not self.resolve_ifdefs or name is None:
            return False
        macro = self.macros.get(name)
        return macro is not None and not macro.conditional

    def _branch(  # noqa: C901, PLR0911
        self, directive: str, name: str | None, original: str, text: str = "", pos: int = 0
    ) -> str:
        """Start the branch `directive` (`ifdef`, `ifndef`, `elsif` or `else`) and return the directive to be kept."""
        if directive in ("ifdef", "ifndef"):
            cond = _Cond(self.state)
            self.conds.append(cond)
        elif self.conds:
            cond = self.conds[-1]
        else:
            # without `ifdef
            return original
        if cond.parent == _INACTIVE or cond.taken:
            self.state = _INACTIVE
            return ""
        # true, false or unknown (None)
        value = True if directive == "else" else None
        if self._is_defined(name):
            value = directive != "ifndef"
        if value is False:
            self.state = _INACTIVE
            return ""
        if value and not cond.unknown:
            # this branch is compiled for sure
            cond.taken = True
            self.state = cond.parent
            return ""
        self.state = _UNCERTAIN
        if value:
            # compiled, if none of the unknown branches before is
            cond.taken = True
            return "`else"
        opened = cond.opened
        cond.opened = cond.unknown = True
        if directive == "ifndef":
            mat = _RE_GUARD.match(text, pos)
            if mat and mat.group(1) == name:
                # include guard or default
                self.state = cond.parent
        if directive == "elsif" and not opened:
            # all branches before have been removed
            return f"`ifdef {name or ''}"
        return original

    def _branch_end(self, directive: str, original: str) -> str:
        """Handle `else` or `endif` and return the directive to be kept."""
        if directive == "else":
            return self._branch(directive, None, original)
        if not self.conds:
            return original
        cond = self.conds.pop()
        self.state = cond.parent
        return original if cond.opened else ""

    # --- macros ---

    def _define(self, name: str, text: str, context: str) -> None:
        if name in self.fixed:
            return
        macro = _parse_define(name, text)
        if macro is None:
            LOGGER.warning("%s: cannot parse definition of macro `%s. Skipped.", context, name)
        elif self.state == _ACTIVE:
            self.ambiguous.discard(name)
            self.macros[name] = macro
        elif name not in self.ambiguous and self.macros.setdefault(name, replace(macro, conditional=True)) != macro:
            LOGGER.debug("%s: macro `%s has conflicting definitions.", context, name)
            self.ambiguous.add(name)
            del self.macros[name]

    def _undef(self, name: str) -> None:
        if name in self.fixed:
            return
        if self.state == _ACTIVE:
            self.ambiguous.discard(name)
            self.macros.pop(name, None)
        elif name in self.macros:
            # maybe it is gone
            self.macros[name] = replace(self.macros[name], conditional=True)

    def _include(self, name: str, context: str, basedir: Path | None) -> None:
        dirs = self.inc_dirs if basedir is None else (basedir, *self.inc_dirs)
        for directory in dirs:
            file_path = directory / name
            if file_path.is_file():
                break
        else:
            LOGGER.info("%s: included file '%s' not found. Its macros are unknown.", context, name)
            return
        resolved = file_path.resolve()
        if resolved in self.included or resolved in self.including:
            return
        if self.state == _ACTIVE:
            self.included.add(resolved)
        state = self.state
        depth = len(self.conds)
        try:
            self.process_file(file_path)
        except (OSError, UnicodeError) as exc:
            LOGGER.warning("%s: cannot read included file '%s': %s", context, file_path, exc)
        # an included file never changes the conditions of the including one
        del self.conds[depth:]
        self.state = state

    def _expand_call(self, text: str, mat: re.Match, context: str) -> tuple[str, int] | None:
        """Expand macro call at `mat`. Return expanded text and end position of the call within `text`."""
        name = mat.group("macro")
        macro = self.macros.get(name)
        if macro is None:
            if name in self.ambiguous:
                # report once
                self.ambiguous.remove(name)
                LOGGER.warning("%s: macro `%s has conflicting definitions. Not expanded.", context, name)
            return None
        if name in self.expanding or len(self.expanding) >= _MAX_DEPTH:
            LOGGER.warning("%s: recursive macro `%s is not expanded.", context, name)
            return None
        if macro.params is None:
            return macro.body, mat.end()
        # function-like macro
        start = _skip_spaces(text, mat.end())
        end = find_closing(text, start)
        if end is None:
            LOGGER.warning("%s: macro `%s requires arguments. Not expanded.", context, name)
            return None
        args = _bind_args(macro, split_args(text[start + 1 : end - 1]))
        if args is None:
            LOGGER.warning("%s: macro `%s is used with wrong number of arguments. Not expanded.", context, name)
            return None
        return _substitute(macro.body, args), end


def collect_defines(
    texts: Iterable[str] = (),
    file_paths: Iterable[Path] = (),
    inc_dirs: Iterable[Path] = (),
    resolve_ifdefs: bool = False,
) -> dict[str, Macro]:
    """Collect all `` `define `` macros from `texts` and `file_paths`, in the given order.

    Included files are searched next to the including file and in `inc_dirs`.
    A macro which is defined with different content under unknown conditions is ambiguous and therefore skipped.
    """
    preproc = _Preprocessor(inc_dirs=inc_dirs, resolve_ifdefs=resolve_ifdefs)
    for text in texts:
        preproc.process(text, "<text>")
        preproc.reset_conds()
    for file_path in file_paths:
        preproc.process_file(file_path)
        preproc.reset_conds()
    for name in sorted(preproc.ambiguous):
        LOGGER.warning("macro `%s has conflicting definitions. Skipped.", name)
    return preproc.macros


def expand(
    text: str,
    macros: Macros | None = None,
    file_path: Path | None = None,
    inc_dirs: Iterable[Path] = (),
    resolve_ifdefs: bool = False,
) -> str:
    """Expand macros and resolve `` `ifdef `` conditions (if `resolve_ifdefs`).

    Macros are taken from `macros`, from the `` `define `` statements within `text` and from the files
    included by `text`. Included files are searched next to `file_path` and in `inc_dirs`.
    `macros` take precedence. Unknown macros are left untouched.
    """
    if "`" not in text:
        return text
    preproc = _Preprocessor(macros, inc_dirs=inc_dirs, resolve_ifdefs=resolve_ifdefs)
    out: list[str] = []
    if file_path:
        preproc.including.append(file_path.resolve())
        preproc.process(text, str(file_path), file_path.parent, out)
    else:
        preproc.process(text, "<text>", None, out)
    # most of the time, there is nothing to do
    return text if len(out) == 1 else "".join(out)


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
