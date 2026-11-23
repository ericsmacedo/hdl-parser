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
from collections.abc import Iterable

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
    """`diagnostic`, found while parsing `context`, as `context:line:col: [file: ]message`."""
    loc = diagnostic.loc
    where = f"{context}:{loc.line}:{loc.col}" if loc else context
    if diagnostic.file:
        where = f"{where}: {diagnostic.file}"
    return f"{where}: {diagnostic.message}"


_LOGLEVELS = {"error": logging.ERROR, "warning": logging.WARNING, "info": logging.INFO}


def log_diagnostic(context: str, diagnostic: dm.Diagnostic, returned: bool = True) -> None:
    """Log `diagnostic`, found while parsing `context`.

    A diagnostic `returned` to the caller is logged at DEBUG level, whatever its severity: a library user should not
    get it on standard error too. One which is not returned is logged at its severity, as that is the only report.
    """
    message = format_diagnostic(context, diagnostic)
    if returned:
        LOGGER.debug("%s", message)
    else:
        LOGGER.log(_LOGLEVELS[diagnostic.severity], "%s", message)


class Diagnostics:
    """Problems Found While Parsing `context` (the file path, or `<text>`).

    `returned`: the items are returned to the caller. Otherwise the log is the only report. See `log_diagnostic`.
    """

    def __init__(self, context: str, returned: bool = True):
        self.context = context
        self.returned = returned
        self.items: list[dm.Diagnostic] = []

    def add(self, code: str, message: str, loc: dm.Location | None = None, file: str = "", item: str = "") -> None:
        """Report the problem `code` at `loc`. See [Diagnostic][hdl_parser.datamodel.Diagnostic] for the arguments."""
        severity = SEVERITIES[code]
        self.items.append(dm.Diagnostic(code=code, severity=severity, message=message, loc=loc, file=file, item=item))
        log_diagnostic(self.context, self.items[-1], returned=self.returned)

    def finish(self, units: Iterable[dm.Module | dm.Package]) -> tuple[dm.Diagnostic, ...]:
        """Return all diagnostics in the order of the file, related to the unit (module, ...) they are located in."""
        modules = tuple(units)

        def position(loc: dm.Location | None) -> tuple[int, int]:
            return (loc.line, loc.col) if loc else (0, 0)

        def module_id(diag: dm.Diagnostic) -> str:
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
            for diag in sorted(self.items, key=lambda diag: position(diag.loc))
        )
