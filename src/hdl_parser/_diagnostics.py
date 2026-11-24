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

"""Diagnostics.

The preprocessor and the parsers report problems to [Diagnostics][hdl_parser._diagnostics.Diagnostics].
Every problem becomes a [Diagnostic][hdl_parser.datamodel.Diagnostic] of the parsed file and a log message at
DEBUG level: the diagnostics are part of the result, the log is for tracing only.
"""

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from . import datamodel as dm

LOGGER = logging.getLogger(__name__)

SEVERITIES: dict[str, dm.Severity] = {
    "macro-not-expanded": "warning",
    "macro-ambiguous": "warning",
    "macro-recursive": "warning",
    "macro-args-missing": "warning",
    "macro-args-count": "warning",
    "macro-bad-define": "warning",
    "include-not-found": "warning",
    "include-unreadable": "warning",
    "header-item-skipped": "warning",
    "statement-skipped": "info",
    "missing-end": "warning",
    "unbalanced-bracket": "warning",
    "no-module": "info",
    "file-not-found": "error",
    "file-unreadable": "error",
    "parse-failed": "error",
    "duplicate-definition": "warning",
    "undefined-module": "warning",
    "multiple-drivers": "warning",
    "filelist-not-found": "error",
    "filelist-unknown": "warning",
    "filelist-variable": "warning",
}
"""Severity of all diagnostic codes. Documented at [Diagnostic][hdl_parser.datamodel.Diagnostic]."""


def shorten(text: str, width: int = 40) -> str:
    """Return `text` on a single line, limited to `width` characters. Used to quote source code."""
    text = " ".join(text.split())
    return text if len(text) <= width else f"{text[: width - 3]}..."


def format_diagnostic(context: str, diagnostic: dm.Diagnostic) -> str:
    """`diagnostic`, found while parsing `context`, as `context:line:col: message`.

    A problem located within an included file: `context: file:line:col: message`.
    A problem of a project (`context` is empty): `file:line:col: message`.
    """
    loc = diagnostic.loc
    file = diagnostic.file
    where = file or context
    if where and loc:
        where = f"{where}:{loc.line}:{loc.col}"
    if file and context and file != context:
        where = f"{context}: {where}"
    return f"{where}: {diagnostic.message}" if where else diagnostic.message


_SILENT: ContextVar[bool] = ContextVar("silent", default=False)


@contextmanager
def silent() -> Iterator[None]:
    """Diagnostics are not logged, as the caller logs them itself (see `log_diagnostic`)."""
    token = _SILENT.set(True)
    try:
        yield
    finally:
        _SILENT.reset(token)


def log_diagnostic(context: str, diagnostic: dm.Diagnostic) -> None:
    """Log `diagnostic`, found while parsing `context`, at DEBUG level, whatever its severity.

    Every diagnostic is returned to the caller. A library user should not get it on standard error too.
    The message starts with the severity: `WARNING file:line:col: message`.
    """
    LOGGER.debug("%s %s", diagnostic.severity.upper(), format_diagnostic(context, diagnostic))


class Diagnostics:
    """Problems Found While Parsing `context`.

    `context` is the parsed file, `<text>`, or empty for the problems of a project: they are located within their
    `file` (a filelist, a file with macros).
    """

    def __init__(self, context: str):
        self.context = context
        self.items: list[dm.Diagnostic] = []

    def add(self, code: str, message: str, loc: dm.Location | None = None, file: str = "", item: str = "") -> None:
        """Report the problem `code` at `loc`. See [Diagnostic][hdl_parser.datamodel.Diagnostic] for the arguments."""
        severity = SEVERITIES[code]
        self.items.append(dm.Diagnostic(code=code, severity=severity, message=message, loc=loc, file=file, item=item))
        if not _SILENT.get():
            log_diagnostic(self.context, self.items[-1])

    def finish(self, units: Iterable[dm.Module | dm.Package]) -> tuple[dm.Diagnostic, ...]:
        """Return all diagnostics in the order of the file, related to the unit (module, ...) they are located in.

        The ones located within an included file follow, by file. They are related to no unit.
        """
        modules = tuple(units)

        def position(loc: dm.Location | None) -> tuple[int, int]:
            return (loc.line, loc.col) if loc else (0, 0)

        def module_id(diag: dm.Diagnostic) -> str:
            if diag.file:
                return ""
            for mod in modules:
                if (
                    mod.loc
                    and diag.loc
                    and position(mod.loc) <= position(diag.loc) < (mod.loc.end_line, mod.loc.end_col)
                ):
                    return mod.id
            return ""

        return tuple(
            diag if diag.item else diag.model_copy(update={"item": module_id(diag)})
            for diag in sorted(self.items, key=lambda diag: (diag.file, position(diag.loc)))
        )
