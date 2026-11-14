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

Set the `id` of all items, after parsing. See [hdl_parser.datamodel.File][] for the format.
"""

import re
from collections.abc import Iterable

from . import datamodel as dm

_ESCAPE = re.compile(r"[.:#~%\s]")


class _Scope:
    """Names Within A File, A Module Or An Instance. A name used again gets a suffix: `a`, `a~2`."""

    __slots__ = ("_prefix", "_seen")

    def __init__(self, prefix: str | None = None):
        self._prefix = "" if prefix is None else f"{prefix}."
        self._seen: dict[str, int] = {}

    def id(self, local: str) -> str:
        count = self._seen[local] = self._seen.get(local, 0) + 1
        return f"{self._prefix}{local}" if count == 1 else f"{self._prefix}{local}~{count}"


def assign_ids(modules: Iterable[dm.Module], casefold: bool = False) -> tuple[dm.Module, ...]:
    """Return `modules` with the `id` of all items set. `casefold`: names are case insensitive (VHDL)."""

    def name(text: str) -> str:
        # percent-encode the separators
        return _ESCAPE.sub(lambda mat: f"%{ord(mat.group()):02X}", text.lower() if casefold else text)

    def named(items, scope):
        return tuple(item.model_copy(update={"id": scope.id(name(item.name))}) for item in items)

    def instance(inst: dm.ModuleInstance, scope: _Scope) -> dm.ModuleInstance:
        inst_id = scope.id(name(inst.name))
        cons = _Scope(inst_id)
        position = 0
        connections = []
        for con in inst.connections:
            if con.port:
                con_id = cons.id(name(con.port))
            else:
                position += 1
                con_id = cons.id(f"#{position}")
            connections.append(con.model_copy(update={"id": con_id}))
        return inst.model_copy(update={"id": inst_id, "connections": tuple(connections)})

    files = _Scope()
    result = []
    for mod in modules:
        mod_id = files.id(name(mod.name))
        scope = _Scope(mod_id)
        update = {
            "id": mod_id,
            "params": named(mod.params, scope),
            "localparams": named(mod.localparams, scope),
            "ports": named(mod.ports, scope),
            "insts": tuple(instance(inst, scope) for inst in mod.insts),
            "unresolved_macros": tuple(
                macro.model_copy(update={"id": scope.id(f"`{name(macro.name)}")}) for macro in mod.unresolved_macros
            ),
        }
        result.append(mod.model_copy(update=update))
    return tuple(result)
