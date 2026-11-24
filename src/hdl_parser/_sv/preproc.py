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

In the *closed world* (`closed_world`) all definitions are known: the given macros, the ones of the text and its
included files, and the names of `maybe_defined` (the macros other files of the design may define). A macro
which is none of them **is** undefined, like for a compiler: `` `ifdef X `` is *false*, `` `ifndef X `` is *true*.
Once an included file is not found, this ends: the file may have defined any macro.

Include guards and defaults (`` `ifndef X `` directly followed by `` `define X ``) are assumed to be compiled.
"""

import logging
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from .._diagnostics import Diagnostics, shorten  # noqa: TID252
from .._tokens import Segment, SourceMap  # noqa: TID252
from ..datamodel import Diagnostic, Location  # noqa: TID252

LOGGER = logging.getLogger(__name__)

_MAX_DEPTH = 32
"""Maximum macro nesting depth."""

_RE_SCAN = re.compile(
    r"""
      (?P<comment>//[^\n]*|/\*.*?\*/)
    | (?P<string>"(?:\\.|[^"\\\n])*")
    | `include[ \t]*"(?P<include>[^"\n]*)"
    | `define[ \t]+(?P<dname>[a-zA-Z_]\w*)(?P<define>(?:\\\r?\n|[^\n])*)
    | `define\b(?P<baddefine>(?:\\\r?\n|[^\n])*)
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
# comment within the arguments of a macro call. strings are matched too, to skip them.
_RE_ARG_COMMENT = re.compile(rf"(?P<string>{_RE_STRING})|//[^\n]*|/\*.*?\*/", re.DOTALL)
# `define behind `ifndef: include guard or default value
_RE_GUARD = re.compile(r"(?:\s|//[^\n]*|/\*.*?\*/)*`define[ \t]+([a-zA-Z_]\w*)", re.DOTALL)
_OPEN = "([{"
_CLOSE = ")]}"

# Code is ...
_ACTIVE = 0  # ... compiled
_UNCERTAIN = 1  # ... compiled or not, it depends on an unknown condition
_INACTIVE = 2  # ... not compiled


def read_text(file_path: Path, encoding: str | None = None) -> str:
    """Read `file_path` as UTF-8 with Latin-1 fallback, or strictly with `encoding` if given."""
    if encoding is not None:
        return file_path.read_text(encoding=encoding)
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="latin-1")


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

RE_DEFINE_NAME = re.compile(r"[a-zA-Z_]\w*(?:\(\s*(?:[a-zA-Z_]\w*\s*(?:,\s*[a-zA-Z_]\w*\s*)*)?\))?")
"""Name of a macro, with its parameters, if it is function-like: `NAME`, `MAX(a, b)`."""


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

    def __init__(  # noqa: PLR0913
        self,
        diagnostics: Diagnostics,
        macros: Macros | None = None,
        inc_dirs: Iterable[Path] = (),
        resolve_ifdefs: bool = False,
        closed_world: bool = False,
        maybe_defined: Iterable[str] = (),
    ):
        self.diagnostics = diagnostics
        self.macros: dict[str, Macro] = dict(macros or {})
        self.ambiguous: set[str] = set()
        # macros handed over are never touched
        self.fixed = frozenset(self.macros)
        self.inc_dirs = tuple(inc_dirs)
        self.resolve_ifdefs = resolve_ifdefs
        # all definitions are known: other macros are undefined
        self.closed_world = closed_world and resolve_ifdefs
        self.maybe_defined = frozenset(maybe_defined)
        self.state = _ACTIVE
        self.conds: list[_Cond] = []
        # macros which are just expanded, files which are just included, files which are done
        self.expanding: list[str] = []
        self.including: list[Path] = []
        self.included: set[Path] = set()
        # all included files which have been read, in the order of reading
        self.includes: list[Path] = []
        # source map of the main output: the output, its segments, its length and the outermost macro call
        self.main_out: list[str] | None = None
        self.segments: list[Segment] = []
        self.out_len = 0
        self.call: Segment | None = None
        # Problems within the main text are located at the outermost directive or macro call: its range within
        # the main text. `smap` creates the location.
        self.site: tuple[int, int] | None = None
        self.smap: SourceMap | None = None
        # Problems within an included file (or a file with macros) are located within it: the texts of the files
        # which are just read, and the current directive within the innermost one (text, start, end, file).
        self.file_texts: list[str] = []
        self.file_site: tuple[str, int, int, str] | None = None
        # location of the definitions which made a macro ambiguous
        self.conflicts: dict[str, tuple[Location | None, str]] = {}

    def process_file(self, file_path: Path, out: list[str] | None = None) -> None:
        """Process the file at `file_path`."""
        text = read_text(file_path)
        self.including.append(file_path.resolve())
        self.file_texts.append(text)
        self.process(text, str(file_path), file_path.parent, out)
        self.file_texts.pop()
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
                    self._emit(out, text[pos:start], pos)
                pos = mat.end()
                if kind == "condend":
                    directive = self._branch_end(mat.group("condend"), mat.group())
                else:
                    directive = self._branch(mat.group("cond"), mat.group("cname"), mat.group(), text, pos)
                if out is not None:
                    self._emit(out, directive, start, pos, "")
            elif self.state != _INACTIVE:
                # problems within a macro or an included file are reported here
                outermost = self.site is None
                if outermost:
                    self.site = (start, mat.end())
                file_site = self.file_site
                if self.file_texts and text is self.file_texts[-1]:
                    self.file_site = (text, start, mat.end(), context)
                if kind == "macro":
                    pos = self._macro(text, mat, pos, context, basedir, out)
                elif kind == "define":
                    self._define(mat.group("dname"), mat.group("define"), context)
                elif kind == "baddefine":
                    statement = shorten(mat.group())
                    self._report("macro-bad-define", f"cannot parse definition '{statement}'. Skipped.", context)
                elif kind == "undef":
                    self._undef(mat.group("undef"))
                else:
                    self._include(mat.group("include"), context, basedir)
                self.file_site = file_site
                if outermost:
                    self.site = None
        if out is not None and self.state != _INACTIVE:
            self._emit(out, text[pos:], pos)

    def _macro(  # noqa: PLR0913
        self, text: str, mat: re.Match, pos: int, context: str, basedir: Path | None, out: list[str] | None
    ) -> int:
        """Replace the macro call at `mat` by its expansion, if possible. Return the position processed up to."""
        result = self._expand_call(text, mat, context)
        if result is None:
            return pos
        expanded, end = result
        start = mat.start()
        name = mat.group("macro")
        if out is not None:
            self._emit(out, text[pos:start], pos)
        # the source map points to the outermost macro call
        mapped = out is not None and out is self.main_out and self.call is None
        if mapped:
            self.call = Segment(0, start, end, name)
        # the replacement is processed like any other text
        self.expanding.append(name)
        self.process(expanded, context, basedir, out)
        self.expanding.pop()
        if mapped:
            self.call = None
        return end

    def _report(self, code: str, message: str, context: str) -> None:
        """Report problem `code` within `context` (the main text or an included file)."""
        loc, file = self._where(context)
        self.diagnostics.add(code, message, loc, file=file)

    def _where(self, context: str) -> tuple[Location | None, str]:
        """Location and file of a problem within `context`, at the current directive or macro call.

        The problem is located where it is: `file` is empty for the main text, `loc` is within `file`.
        """
        if context == self.diagnostics.context:
            # main text: at the outermost directive or macro call
            loc = self.smap.source_location(*self.site) if self.smap and self.site else None
            return loc, ""
        if self.file_site is None:
            # text, which is no file
            return None, ""
        text, start, end, file = self.file_site
        return _location(text, start, end), file

    def _emit(
        self, out: list[str], chunk: str, src_start: int, src_end: int | None = None, macro: str | None = None
    ) -> None:
        """Append `chunk` to `out`. `chunk` is `text[src_start:]`, or replaces `text[src_start:src_end]`.

        Only the main output is tracked by the source map.
        """
        out.append(chunk)
        if out is not self.main_out or not chunk:
            return
        if self.call is not None:
            # created by a macro call
            seg = self.call._replace(start=self.out_len)
        elif macro is None:
            seg = Segment(self.out_len, src_start, src_start + len(chunk))
        else:
            seg = Segment(self.out_len, src_start, src_end if src_end is not None else src_start, macro)
        segments = self.segments
        if not segments or segments[-1][1:] != seg[1:] or seg.macro is None:
            segments.append(seg)
        self.out_len += len(chunk)

    # --- conditions ---

    def reset_conds(self) -> None:
        """Forget all open conditions."""
        self.conds.clear()
        self.state = _ACTIVE

    def _is_defined(self, name: str | None) -> bool | None:
        """`name` is known to be defined (`True`), known to be undefined (`False`) or unknown (`None`)."""
        if not self.resolve_ifdefs or name is None:
            return None
        macro = self.macros.get(name)
        if macro is not None:
            return None if macro.conditional else True
        if self.closed_world and name not in self.ambiguous and name not in self.maybe_defined:
            return False
        return None

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
        defined = self._is_defined(name)
        if defined is not None:
            value = defined != (directive == "ifndef")
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
            self._report("macro-bad-define", f"cannot parse definition of macro `{name}. Skipped.", context)
        elif self.state == _ACTIVE:
            self.ambiguous.discard(name)
            self.macros[name] = macro
        elif name not in self.ambiguous and self.macros.setdefault(name, replace(macro, conditional=True)) != macro:
            LOGGER.debug("%s: macro `%s has conflicting definitions.", context, name)
            self.ambiguous.add(name)
            self.conflicts[name] = self._where(context)
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
            self._report("include-not-found", f"included file '{name}' not found. Its macros are unknown.", context)
            # any macro may be defined by now
            self.closed_world = False
            return
        resolved = file_path.resolve()
        if resolved in self.included or resolved in self.including:
            return
        if self.state == _ACTIVE:
            self.included.add(resolved)
        state = self.state
        depth = len(self.conds)
        if resolved not in self.includes:
            self.includes.append(resolved)
        try:
            self.process_file(file_path)
        except OSError as exc:
            self._report("include-unreadable", f"cannot read included file '{file_path}': {exc}", context)
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
                self._report("macro-ambiguous", f"macro `{name} has conflicting definitions. Not expanded.", context)
            return None
        if name in self.expanding or len(self.expanding) >= _MAX_DEPTH:
            self._report("macro-recursive", f"recursive macro `{name} is not expanded.", context)
            return None
        if macro.params is None:
            return macro.body, mat.end()
        # function-like macro
        start = _skip_spaces(text, mat.end())
        end = find_closing(text, start)
        if end is None:
            self._report("macro-args-missing", f"macro `{name} requires arguments. Not expanded.", context)
            return None
        arg_text = _RE_ARG_COMMENT.sub(lambda mat: mat.group("string") or " ", text[start + 1 : end - 1])
        args = _bind_args(macro, split_args(arg_text))
        if args is None:
            self._report(
                "macro-args-count", f"macro `{name} is used with wrong number of arguments. Not expanded.", context
            )
            return None
        # Macros within arguments are expanded first. So a macro may be used within its own arguments.
        for pname, arg in args.items():
            if "`" in arg:
                out: list[str] = []
                self.process(arg, context, out=out)
                args[pname] = "".join(out)
        return _substitute(macro.body, args), end


def collect_defines(
    texts: Iterable[str] = (),
    file_paths: Iterable[Path] = (),
    inc_dirs: Iterable[Path] = (),
    resolve_ifdefs: bool = False,
) -> tuple[dict[str, Macro], tuple[Diagnostic, ...]]:
    """Collect all `` `define `` macros from `texts` and `file_paths`, in the given order. Return them and the problems.

    Included files are searched next to the including file and in `inc_dirs`.
    A macro which is defined with different content under unknown conditions is ambiguous and therefore skipped.
    """
    # problems of the project: located within their file
    diagnostics = Diagnostics("")
    preproc = _Preprocessor(diagnostics, inc_dirs=inc_dirs, resolve_ifdefs=resolve_ifdefs)
    for text in texts:
        preproc.process(text, "<text>")
        preproc.reset_conds()
    for file_path in file_paths:
        preproc.process_file(file_path)
        preproc.reset_conds()
    for name in sorted(preproc.ambiguous):
        loc, file = preproc.conflicts.get(name, (None, ""))
        diagnostics.add("macro-ambiguous", f"macro `{name} has conflicting definitions. Skipped.", loc, file=file)
    return preproc.macros, tuple(diagnostics.items)


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
    return expand_mapped(text, macros, file_path, inc_dirs, resolve_ifdefs)[0]


def expand_mapped(  # noqa: PLR0913
    text: str,
    macros: Macros | None = None,
    file_path: Path | None = None,
    inc_dirs: Iterable[Path] = (),
    resolve_ifdefs: bool = False,
    diagnostics: Diagnostics | None = None,
    includes: list[Path] | None = None,
    closed_world: bool = False,
    maybe_defined: Iterable[str] = (),
) -> tuple[str, SourceMap]:
    """Like [expand][hdl_parser._sv.preproc.expand], but also return the source map of the result.

    Problems are reported to `diagnostics`. The included files which have been read are added to `includes`.
    With `closed_world`, any macro which is neither known nor named by `maybe_defined` is undefined.
    """
    smap = SourceMap(text)
    if "`" not in text:
        return text, smap
    context = str(file_path) if file_path else "<text>"
    preproc = _Preprocessor(
        diagnostics or Diagnostics(context), macros, inc_dirs, resolve_ifdefs, closed_world, maybe_defined
    )
    preproc.smap = smap
    out: list[str] = []
    preproc.main_out = out
    if file_path:
        preproc.including.append(file_path.resolve())
        preproc.process(text, context, file_path.parent, out)
    else:
        preproc.process(text, context, None, out)
    # most of the time, there is nothing to do
    if includes is not None:
        includes += preproc.includes
    if len(out) == 1:
        return text, smap
    smap.set_segments(preproc.segments)
    return "".join(out), smap


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
    """Iterate over `text` and yield `(pos, char, level)` for everything outside of strings and comments."""
    level = 0
    end = len(text)
    while pos < end:
        char = text[pos]
        if char == '"':
            pos += 1
            while pos < end and text[pos] != '"':
                pos += 2 if text[pos] == "\\" else 1
        elif char == "/" and text.startswith(("//", "/*"), pos):
            # skip comment
            if text[pos + 1] == "/":
                stop = text.find("\n", pos)
            else:
                stop = text.find("*/", pos + 2) + 1
            pos = stop if stop > 0 else end
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


def defined_names(file_paths: Iterable[Path], inc_dirs: Iterable[Path] = ()) -> frozenset[str]:
    """Names of all macros which are `` `define ``d by `file_paths` and the files they include, under any condition.

    Included files are searched next to the including file and in `inc_dirs`. Files which cannot be read are
    skipped.
    """
    dirs = tuple(inc_dirs)
    names: set[str] = set()
    done: set[Path] = set()
    todo = [Path(path) for path in file_paths]
    while todo:
        path = todo.pop()
        resolved = path.resolve()
        if resolved in done:
            continue
        done.add(resolved)
        try:
            text = read_text(path)
        except (OSError, UnicodeError):
            continue
        if "`" not in text:
            continue
        for mat in _RE_SCAN.finditer(text):
            kind = mat.lastgroup
            if kind == "define":
                names.add(mat.group("dname"))
            elif kind == "include":
                name = mat.group("include")
                for directory in (path.parent, *dirs):
                    if (directory / name).is_file():
                        todo.append(directory / name)
                        break
    return frozenset(names)


def _location(text: str, start: int, end: int) -> Location:
    """Location of `text[start:end]`."""
    line = text.count("\n", 0, start) + 1
    col = start - text.rfind("\n", 0, start)
    end_line = line + text.count("\n", start, end)
    end_col = end - text.rfind("\n", 0, end)
    return Location(line=line, col=col, end_line=end_line, end_col=end_col)
