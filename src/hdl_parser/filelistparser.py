# MIT License
#
# Copyright (c) 2025 ericsmacedo
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

"""File List Parser."""

import logging
import re
from collections.abc import Iterable
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_RE_COMMENT = re.compile(r"\A(.*?)(\s*(#|//).*)\Z")
_RE_FILELIST = re.compile(r"\A-([fF])\s+(.*?)\Z")
_RE_INCDIR = re.compile(r'\A[+\-]incdir[+\-\s]"?(?P<incdir>.*?)"?\Z')
_RE_FILE = re.compile(r"\A((-sv|-v)\s+)?(?P<filepath>[^+-].*?)\Z")


def parse_filelist(  # type: ignore[override]
    filepaths: list[Path],
    inc_dirs: list[Path],
    filepath: Path,
):
    """Read File List File.

    Args:
        filepaths: File Paths Container.
        inc_dirs: Include Directories Container.
        filepath: File to be parsed.
    """
    with filepath.open(encoding="utf-8") as file:
        basepath = filepath.parent
        _parse(filepaths, inc_dirs, basepath, file)

    with filepath.open(encoding="utf-8") as file:
        basepath = filepath.parent
        _parse(filepaths, inc_dirs, basepath, file, context=str(filepath))


def _parse(
    filepaths: list[Path],
    inc_dirs: list[Path],
    basedir: Path,
    items: Iterable[str | Path],
    context: str = "",
):
    """File List File.

    Args:
        filepaths: File Paths Container.
        inc_dirs: Include Directories Container.
        basedir: Base Directory for Relative Paths.
        items: Items to be parsed.
        context: Context for error reporting.
    """
    for lineno, item in enumerate(items, 1):
        line = str(item).strip()
        # comment
        mat = _RE_COMMENT.match(line)
        if mat:
            line = mat.group(1).strip()
        if not line:
            continue
        # -f
        mat = _RE_FILELIST.match(line)
        if mat:
            filelistpath = basedir / mat.group(2)
            parse_filelist(filepaths, inc_dirs, filelistpath)
            continue
        # -incdir
        mat = _RE_INCDIR.match(line)
        if mat:
            incdir = basedir / mat.group("incdir")
            if incdir not in inc_dirs:
                inc_dirs.append(incdir)
            continue
        # file
        mat = _RE_FILE.match(line)
        if mat:
            filepath = basedir / mat.group("filepath")
            if filepath not in filepaths:
                filepaths.append(filepath)
            continue
        LOGGER.warning("%s:%d Cannot parse %s", context, lineno, line)
