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

"""File List Parser.

A filelist names the files of a design, one per line, together with options of the tools reading it:

| Line                              | Meaning                                                                  |
| --------------------------------- | ------------------------------------------------------------------------ |
| `rtl/top.sv`                      | File                                                                     |
| `-f other.f`, `-F other.f`        | Another filelist                                                         |
| `+incdir+dir1+dir2`, `-incdir dir`, `-I dir` | Include directories                                           |
| `+define+NAME=VALUE+OTHER`, `-define NAME=VALUE`, `-D NAME` | Macros                                         |
| `-v lib.v`                        | Library file: its modules are used, if they are not defined elsewhere    |
| `-y dir`                          | Library directory: a module which is not defined is searched for there   |
| `+libext+.v+.sv`                  | Extensions of the files within library directories                       |
| `// comment`, `# comment`         | Comment                                                                  |

Relative paths are relative to the directory of the filelist they are written in.
Environment variables (`$NAME`, `${NAME}`, `$(NAME)`) are replaced. A line with a variable which is not defined is
skipped and reported, like everything else which is not understood.
"""

import logging
import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pydantic as pyd

from . import datamodel as dm
from ._diagnostics import Diagnostics
from ._sv.preproc import RE_DEFINE_NAME

LOGGER = logging.getLogger(__name__)

_RE_COMMENT = re.compile(r"\A(.*?)(\s*(#|//).*)\Z")
_RE_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|\((\w+)\)|(\w+))")
_HDL_SUFFIXES = frozenset((".sv", ".v", ".vhd", ".vhdl", ".svh", ".vh"))
# options with one argument: -f, -F, ...
_FILELIST = frozenset(("-f", "-F"))
_INCDIR = frozenset(("-incdir", "-I"))
_DEFINE = frozenset(("-define", "-D"))
_ONE_ARGUMENT = frozenset((*_FILELIST, *_INCDIR, *_DEFINE, "-v", "-y"))
# options without relevance
_IGNORED = frozenset(("-sv", "-sverilog", "-v2k", "-v2k5", "-vhdl", "-93", "-2008"))
DEFAULT_LIB_EXTS = (".v", ".sv")
"""Extensions of the files within library directories, if the filelist does not state them."""


class FileList(pyd.BaseModel):
    """Content Of A Filelist, Including The Filelists It Names.

    Attributes:
        files: Files.
        inc_dirs: Include directories.
        defines: Macros, by name.
        lib_files: Library files. Not part of `files`.
        lib_dirs: Library directories.
        lib_exts: Extensions of the files within library directories.
        diagnostics: Problems: everything which is not understood. Located within their `file`, the filelist.
    """

    model_config = pyd.ConfigDict(frozen=True, extra="forbid")

    files: tuple[Path, ...] = ()
    inc_dirs: tuple[Path, ...] = ()
    defines: dict[str, str] = {}
    lib_files: tuple[Path, ...] = ()
    lib_dirs: tuple[Path, ...] = ()
    lib_exts: tuple[str, ...] = ()
    diagnostics: tuple[dm.Diagnostic, ...] = ()


@dataclass
class _Content:
    """Content of `FileList`, while it is read."""

    files: list[Path] = field(default_factory=list)
    inc_dirs: list[Path] = field(default_factory=list)
    defines: dict[str, str] = field(default_factory=dict)
    lib_files: list[Path] = field(default_factory=list)
    lib_dirs: list[Path] = field(default_factory=list)
    lib_exts: list[str] = field(default_factory=list)
    diagnostics: list[dm.Diagnostic] = field(default_factory=list)


def read_filelist(filelist_path: Path | str, env: Mapping[str, str] | None = None) -> FileList:
    """Read the filelist at `filelist_path`, and all filelists it names.

    Args:
        filelist_path: Path to the filelist.

    Keyword Args:
        env: Environment variables. The ones of the process by default.

    A filelist which cannot be read is reported in `diagnostics` (`filelist-not-found`).
    """
    content = _Content()
    reader = _Reader(content, os.environ if env is None else env)
    reader.read(Path(filelist_path))
    return FileList(**vars(content))


def parse_filelist(filepaths: list[Path], inc_dirs: list[Path], filepath: Path) -> FileList:
    """Read File List File.

    Args:
        filepaths: File Paths Container. Library files are added too.
        inc_dirs: Include Directories Container.
        filepath: File to be parsed.

    Returns:
        Everything the filelist contains, including its problems (`diagnostics`).
        See [read_filelist][hdl_parser.filelistparser.read_filelist].
    """
    filelist = read_filelist(filepath)
    filepaths += [path for path in (*filelist.files, *filelist.lib_files) if path not in filepaths]
    inc_dirs += [path for path in filelist.inc_dirs if path not in inc_dirs]
    return filelist


def _add(items: list, item) -> None:
    if item not in items:
        items.append(item)


class _Reader:
    """Read Filelists Into `filelist`."""

    def __init__(self, filelist: _Content, env: Mapping[str, str]):
        self.filelist = filelist
        self.env = env
        # filelists which are just read, variables which have been reported
        self.reading: list[Path] = []
        self.undefined: set[str] = set()

    def read(self, path: Path, at: tuple[Path, int, str] | None = None) -> None:
        """Read filelist at `path`. `at`: filelist, line number and line naming it."""
        resolved = path.resolve()
        if resolved in self.reading:
            return
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            where = at or (path, 0, "")
            self._report(*where, "filelist-not-found", f"cannot read filelist '{path}': {exc}")
            return
        self.reading.append(resolved)
        for number, line in enumerate(text.splitlines(), 1):
            self._read_line(path, number, line)
        self.reading.pop()

    def _report(self, path: Path, number: int, line: str, code: str, message: str) -> None:
        loc = dm.Location(line=number, col=1, end_line=number, end_col=len(line) + 1) if number else None
        # a problem of the project, located within the filelist
        diagnostics = Diagnostics("")
        diagnostics.add(code, message, loc, file=str(path))
        self.filelist.diagnostics += diagnostics.items

    def _define(self, path: Path, number: int, line: str, text: str) -> None:
        """Add the macro `NAME` or `NAME=VALUE`. One which has no valid name is reported."""
        name, _, value = text.partition("=")
        if RE_DEFINE_NAME.fullmatch(name):
            self.filelist.defines[name] = value
        else:
            self._report(path, number, line, "macro-bad-define", f"cannot parse definition '{text}'. Skipped.")

    def _defined(self, path: Path, number: int, line: str) -> bool:
        """All environment variables of `line` are defined. The ones which are not are reported."""
        missing = [name for groups in _RE_VARIABLE.findall(line) for name in groups if name and name not in self.env]
        for name in missing:
            if name not in self.undefined:
                self.undefined.add(name)
                message = f"environment variable '{name}' is not defined. All lines using it are skipped."
                self._report(path, number, line, "filelist-variable", message)
        return not missing

    def _expand(self, word: str) -> str:
        """Replace the environment variables of `word`."""
        return _RE_VARIABLE.sub(lambda mat: self.env[mat.group(1) or mat.group(2) or mat.group(3)], word)

    def _read_line(self, path: Path, number: int, line: str) -> None:  # noqa: C901, PLR0912
        mat = _RE_COMMENT.match(line)
        text = (mat.group(1) if mat else line).strip()
        if not text or not self._defined(path, number, text):
            return
        # The values of variables are never split, and may contain anything: spaces, quotes, backslashes.
        words = [self._expand(word) for word in _split(text)]
        filelist = self.filelist
        basedir = path.parent
        idx = 0
        while idx < len(words):
            word = words[idx]
            # argument of an option: -f file
            arg = words[idx + 1] if idx + 1 < len(words) else ""
            idx += 1
            if word in _IGNORED:
                continue
            if word.startswith("+"):
                name, *values = word[1:].split("+")
                values = [value for value in values if value]
                if name == "incdir":
                    for value in values:
                        _add(filelist.inc_dirs, basedir / value)
                elif name == "define":
                    for value in values:
                        self._define(path, number, line, value)
                elif name == "libext":
                    for value in values:
                        _add(filelist.lib_exts, value)
                else:
                    self._report(path, number, line, "filelist-unknown", f"option '{word}' is not understood.")
            elif word in _ONE_ARGUMENT and not arg:
                self._report(path, number, line, "filelist-unknown", f"option '{word}' has no argument.")
            elif word in _FILELIST:
                self.read(basedir / arg, (path, number, line))
                idx += 1
            elif word in _INCDIR:
                _add(filelist.inc_dirs, basedir / arg)
                idx += 1
            elif word in _DEFINE:
                self._define(path, number, line, arg)
                idx += 1
            elif word == "-v":
                _add(filelist.lib_files, basedir / arg)
                idx += 1
            elif word == "-y":
                _add(filelist.lib_dirs, basedir / arg)
                idx += 1
            elif word.startswith("-"):
                self._report(path, number, line, "filelist-unknown", f"option '{word}' is not understood.")
                # its argument is no file
                if arg and not arg.startswith(("-", "+")) and Path(arg).suffix not in _HDL_SUFFIXES:
                    idx += 1
            else:
                _add(filelist.files, basedir / word)


def _split(text: str) -> list[str]:
    """Split `text` at white space. Quotes keep words together. A backslash is part of a path, and no escape."""
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    try:
        return list(lexer)
    except ValueError:
        # a quote which is never closed
        return text.split()
