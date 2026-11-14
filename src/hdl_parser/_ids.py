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

"""Identifiers.

The parsers create the `id` of all items with a [Scope][hdl_parser._ids.Scope] per module and instance.
See [hdl_parser.datamodel.File][] for the format.
"""

import re

_ESCAPE = re.compile(r"[.:#~%\s]")


def escape(name: str) -> str:
    """Percent-encode the separators within `name`."""
    return _ESCAPE.sub(lambda mat: f"%{ord(mat.group()):02X}", name)


class Scope:
    """Names Within A Module, An Instance Or A File. A name used again gets a suffix: `a`, `a~2`.

    Args:
        prefix: Identifier of the scope, `None` for the top level.
        casefold: Names are case insensitive (VHDL).
    """

    __slots__ = ("_casefold", "_position", "_prefix", "_seen")

    def __init__(self, prefix: str | None = None, casefold: bool = False):
        self._prefix = "" if prefix is None else f"{prefix}."
        self._casefold = casefold
        self._seen: dict[str, int] = {}
        self._position = 0

    def _unique(self, local: str) -> str:
        count = self._seen[local] = self._seen.get(local, 0) + 1
        return f"{self._prefix}{local}" if count == 1 else f"{self._prefix}{local}~{count}"

    def id(self, name: str) -> str:
        """Identifier of the item `name`."""
        return self._unique(escape(name.lower() if self._casefold else name))

    def macro_id(self, name: str) -> str:
        """Identifier of a call of the macro `name`."""
        return self._unique(f"`{escape(name)}")

    def connection_id(self, port: str) -> str:
        """Identifier of a connection to `port`, by position if `port` is empty."""
        if port:
            return self.id(port)
        self._position += 1
        return self._unique(f"#{self._position}")

    def scope(self, id_: str) -> "Scope":
        """Scope of the item with identifier `id_`."""
        return Scope(id_, self._casefold)
