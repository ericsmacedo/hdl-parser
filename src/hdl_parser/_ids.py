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


class _Assigner:
    """Set the `id` of items. `casefold`: names are case insensitive (VHDL)."""

    def __init__(self, casefold: bool):
        self.casefold = casefold
        # modules and packages share the names of the file
        self.files = _Scope()

    def name(self, text: str) -> str:
        """Name as part of an identifier: the separators are percent-encoded."""
        return _ESCAPE.sub(lambda mat: f"%{ord(mat.group()):02X}", text.lower() if self.casefold else text)

    def named(self, items, scope: _Scope):
        return tuple(item.model_copy(update={"id": scope.id(self.name(item.name))}) for item in items)

    def typedefs(self, typedefs: tuple[dm.Typedef, ...], scope: _Scope) -> tuple[dm.Typedef, ...]:
        result = []
        for typedef in typedefs:
            typedef_id = scope.id(self.name(typedef.name))
            update = {"id": typedef_id, "members": self.named(typedef.members, _Scope(typedef_id))}
            result.append(typedef.model_copy(update=update))
        return tuple(result)

    def functions(self, functions: tuple[dm.Function, ...], scope: _Scope) -> tuple[dm.Function, ...]:
        result = []
        for function in functions:
            function_id = scope.id(self.name(function.name))
            update = {"id": function_id, "args": self.named(function.args, _Scope(function_id))}
            result.append(function.model_copy(update=update))
        return tuple(result)

    def connections(self, cons: tuple[dm.Connection, ...], scope: _Scope, by_order: str) -> tuple[dm.Connection, ...]:
        position = 0
        result = []
        for con in cons:
            if con.port:
                con_id = scope.id(self.name(con.port))
            else:
                position += 1
                con_id = scope.id(f"{by_order}{position}")
            result.append(con.model_copy(update={"id": con_id}))
        return tuple(result)

    def hierarchical(self, item: dm.ModuleInstance | dm.Signal | dm.Process, name: str = "") -> str:
        """Hierarchical name: it includes the labels of the generate blocks."""
        labels = [self.name(generate.name) for generate in item.generates if generate.name]
        return ".".join((*labels, name or self.name(item.name)))

    def processes(self, processes: tuple[dm.Process, ...], scope: _Scope) -> tuple[dm.Process, ...]:
        result = []
        for number, process in enumerate(processes, 1):
            # blocks without label are numbered
            name = "" if process.name else f"#always{number}"
            result.append(process.model_copy(update={"id": scope.id(self.hierarchical(process, name))}))
        return tuple(result)

    def signals(self, signals: tuple[dm.Signal, ...], scope: _Scope) -> tuple[dm.Signal, ...]:
        return tuple(signal.model_copy(update={"id": scope.id(self.hierarchical(signal))}) for signal in signals)

    def instance(self, inst: dm.ModuleInstance, scope: _Scope) -> dm.ModuleInstance:
        inst_id = scope.id(self.hierarchical(inst))
        # parameters and ports share the names of the instantiated module
        inst_scope = _Scope(inst_id)
        update = {
            "id": inst_id,
            "params": self.connections(inst.params, inst_scope, "#p"),
            "connections": self.connections(inst.connections, inst_scope, "#"),
        }
        return inst.model_copy(update=update)

    def package(self, pkg: dm.Package) -> dm.Package:
        pkg_id = self.files.id(self.name(pkg.name))
        scope = _Scope(pkg_id)
        update = {
            "id": pkg_id,
            "params": self.named(pkg.params, scope),
            "localparams": self.named(pkg.localparams, scope),
            "typedefs": self.typedefs(pkg.typedefs, scope),
            "functions": self.functions(pkg.functions, scope),
        }
        return pkg.model_copy(update=update)

    def module(self, mod):
        """Module or interface."""
        mod_id = self.files.id(self.name(mod.name))
        scope = _Scope(mod_id)
        update: dict = {
            "id": mod_id,
            "params": self.named(mod.params, scope),
            "localparams": self.named(mod.localparams, scope),
            "ports": self.named(mod.ports, scope),
            "signals": self.signals(mod.signals, scope),
            "typedefs": self.typedefs(mod.typedefs, scope),
            "functions": self.functions(mod.functions, scope),
            "processes": self.processes(mod.processes, scope),
            "insts": tuple(self.instance(inst, scope) for inst in mod.insts),
            "unresolved_macros": tuple(
                macro.model_copy(update={"id": scope.id(f"`{self.name(macro.name)}")})
                for macro in mod.unresolved_macros
            ),
        }
        if isinstance(mod, dm.Interface):
            update["modports"] = self.modports(mod.modports, scope)
        return mod.model_copy(update=update)

    def modports(self, modports: tuple[dm.Modport, ...], scope: _Scope) -> tuple[dm.Modport, ...]:
        result = []
        for modport in modports:
            modport_id = scope.id(self.name(modport.name))
            update = {"id": modport_id, "ports": self.named(modport.ports, _Scope(modport_id))}
            result.append(modport.model_copy(update=update))
        return tuple(result)


def assign_ids(file: dm.File, casefold: bool = False) -> dm.File:
    """Return `file` with the `id` of all items set. `casefold`: names are case insensitive (VHDL)."""
    assigner = _Assigner(casefold)
    update = {
        "modules": tuple(assigner.module(mod) for mod in file.modules),
        "interfaces": tuple(assigner.module(mod) for mod in file.interfaces),
        "packages": tuple(assigner.package(pkg) for pkg in file.packages),
    }
    return file.model_copy(update=update)
