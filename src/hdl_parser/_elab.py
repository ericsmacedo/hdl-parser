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

"""Elaboration: The Values Of Parameters And The Number Of Bits Of Ports, Per Instance.

A [Scope][hdl_parser._elab.Scope] knows the names of one module instance or package: its parameters with the
values given by the instance, its local parameters, the members of its enumerations and what it imports.
Expressions are evaluated by [hdl_parser._expr][] within a scope.

Nothing is ever guessed: what cannot be evaluated for sure stays unknown, with the reason.
"""

import re
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

from . import datamodel as dm
from ._expr import Num, Scalar, Unknown, evaluate, evaluate_dims

if TYPE_CHECKING:
    from .project import Definition, Project

# number of bits of the built-in types
_SV_BITS = {
    **dict.fromkeys(("logic", "bit", "reg", "wire", "tri", "uwire", "wand", "wor", "var", "supply0", "supply1"), 1),
    "byte": 8,
    "shortint": 16,
    "int": 32,
    "integer": 32,
    "longint": 64,
    "time": 64,
}
_VHDL_BITS = dict.fromkeys(("std_logic", "std_ulogic", "bit"), 1)
_VHDL_VECTORS = frozenset(("std_logic_vector", "std_ulogic_vector", "bit_vector", "unsigned", "signed"))
_SV_QUALIFIERS = frozenset(("signed", "unsigned", "var", "const", "packed"))
_RE_SV_TYPE = re.compile(r"\s*(?P<name>[\w$:.\s]*?)\s*(?P<dims>(?:\[.*\])?)\s*\Z", re.DOTALL)
_RE_VHDL_ARRAY = re.compile(r"array\s*\((?P<range>.*?)\)\s*of\s+(?P<type>.*)\Z", re.DOTALL | re.IGNORECASE)
_RE_VHDL_TYPE = re.compile(r"(?P<name>[\w.]+)\s*(?:\((?P<range>.*)\))?\s*\Z", re.DOTALL)
_RE_VHDL_RANGE = re.compile(r"\s*\b(?:downto|to)\b\s*", re.IGNORECASE)


def _value(num: Num, expr: str) -> dm.Value:
    return dm.Value(expr=expr, value=num.value)


class Scope:
    """Names Of One Module Instance Or Package.

    Args:
        elab: Elaboration of the project.
        definition: The module, interface or package.
        overrides: Values of parameters, given by the instance.
    """

    def __init__(self, elab: "Elaboration", definition: "Definition", overrides: Mapping[str, dm.Value] | None = None):
        self.elab = elab
        self.definition = definition
        self.lang = definition.file.lang
        self.units: list[dm.Module | dm.Package] = [definition.unit, *(module for _, module in definition.bodies)]
        self.overrides = {self.key(name): value for name, value in (overrides or {}).items()}
        # parameters and local parameters in the order of their declaration, by name
        params = [param for unit in self.units for param in (*unit.params, *unit.localparams)]
        params.sort(key=lambda param: (param.loc.line, param.loc.col) if param.loc else (0, 0))
        self.params: dict[str, dm.Param] = {}
        for param in params:
            self.params.setdefault(self.key(param.name), param)
        self.typedefs = {self.key(typedef.name): typedef for unit in self.units for typedef in unit.typedefs}
        # what has been evaluated: values, numbers (or the reason they are not known), and what is just evaluated
        self.values: dict[str, dm.Value] = {}
        self.nums: dict[str, Num | Unknown] = {}
        self.evaluating: set[str] = set()
        self._members: dict[str, Num | Unknown] | None = None

    def key(self, name: str) -> str:
        """Name as it is looked up: VHDL names are not case sensitive."""
        return name.lower() if self.lang == "vhdl" else name

    # --- expressions ---

    def evaluate(self, expr: str, lang: str | None = None) -> Num:
        """Value of `expr` within this scope. Raises `Unknown`."""
        return evaluate(expr, lang or self.lang, self)

    def dims(self, dims: str) -> int:
        """Number of elements of the dimensions `dims`. Raises `Unknown`."""
        return evaluate_dims(dims, self.lang, self) if dims else 1

    def value_of(self, expr: str, lang: str | None = None) -> dm.Value:
        """Value of `expr` within this scope. An expression which is not known has no value, but a reason."""
        try:
            return _value(self.evaluate(expr, lang), expr)
        except Unknown as exc:
            return dm.Value(expr=expr, unknown=str(exc))

    # --- names (see hdl_parser._expr.Names) ---

    def value(self, path: tuple[str, ...]) -> Num:
        """Value of the name `path`: `("WIDTH",)`, `("pkg", "WIDTH")`. Raises `Unknown`."""
        if len(path) == 1:
            return self.lookup(self.key(path[0]), path[0])
        # pkg::name, or lib.pkg.name
        package = self.elab.package(path[-2], self.lang)
        if package is None:
            raise Unknown(f"package '{path[-2]}' is not defined in the project")
        return package.own(package.key(path[-1]), "::".join(path[-2:]))

    def lookup(self, key: str, name: str) -> Num:
        """Value of `name`: a parameter, a member of an enumeration, or an imported name."""
        if self.has(key):
            return self.own(key, name)
        for package, imported in self.imports():
            package_key = package.key(name)
            if imported in ("*", package_key) and package.has(package_key):
                return package.own(package_key, name)
        raise Unknown(f"'{name}' is not known")

    def imports(self) -> Iterator[tuple["Scope", str]]:
        """Imported packages which are defined in the project, with the imported name (`*` for all)."""
        for unit in self.units:
            for text in unit.imports:
                # pkg::name, or lib.pkg.name
                *_, package_name, imported = re.split(r"::|\.", text) if ("::" in text or "." in text) else ("", text)
                package = self.elab.package(package_name, self.lang)
                if package is not None and package is not self:
                    yield package, "*" if imported in ("*", "all") else package.key(imported)

    def has(self, key: str) -> bool:
        """This scope declares `key`."""
        return key in self.params or key in self.members

    def own(self, key: str, name: str) -> Num:
        """Value of the parameter or member `key` of this scope."""
        if key in self.params:
            num = self.param(key)
        else:
            num = self.members.get(key) or Unknown(f"'{name}' is not known")
            if key not in self.members:
                raise num
        if isinstance(num, Unknown):
            # the reason at the end of the chain is the one of interest
            reason = str(num).rpartition(" is not known: ")[2]
            raise Unknown(f"'{name}' is not known: {reason}")
        return num

    # --- parameters ---

    def param(self, key: str) -> Num | Unknown:
        """Value of the parameter `key`, or the reason it is not known."""
        if key not in self.nums:
            if key in self.evaluating:
                return Unknown("it depends on itself")
            self.evaluating.add(key)
            try:
                num = self._param(self.params[key], self.overrides.get(key))
                self.nums[key] = num
                self.values[key] = dm.Value(expr=self._expr(key), value=num.value)
            except Unknown as exc:
                self.nums[key] = exc
                self.values[key] = dm.Value(expr=self._expr(key), unknown=str(exc))
            self.evaluating.discard(key)
        return self.nums[key]

    def _expr(self, key: str) -> str:
        override = self.overrides.get(key)
        return override.expr if override else self.params[key].default

    def _param(self, param: dm.Param, override: dm.Value | None) -> Num:
        if override is not None:
            if override.value is None:
                raise Unknown(override.unknown or "the value given by the instance is not known")
            return Num(override.value)
        if not param.default:
            raise Unknown("no value")
        if param.ptype == "type":
            # the value of a type parameter is the type
            return Num(" ".join(param.default.split()))
        num = self.evaluate(param.default)
        if num.fill:
            # '0 and '1 fill the parameter
            width = self.type_bits(param.ptype or "logic", param.dim) if self.lang == "sv" else 0
            return Num(((1 << width) - 1) if num.value else 0, width)
        return num

    def all_params(self) -> dict[str, dm.Value]:
        """Values of all parameters and local parameters, by name, in the order of their declaration."""
        for key in self.params:
            self.param(key)
        return {param.name: self.values[key] for key, param in self.params.items()}

    # --- enumerations ---

    @property
    def members(self) -> dict[str, Num | Unknown]:
        """Values of the members of all enumerations, by name."""
        if self._members is None:
            self._members = {}
            for typedef in self.typedefs.values():
                if typedef.kind == "enum":
                    self._add_members(typedef, self._members)
        return self._members

    def _add_members(self, typedef: dm.Typedef, members: dict[str, Num | Unknown]) -> None:
        if self.lang == "vhdl":
            # an enumeration literal is its own value
            for member in typedef.members:
                members.setdefault(self.key(member.name), Num(member.name.lower()))
            return
        last: int | None = -1
        for member in typedef.members:
            names = [member.name]
            if member.dim_unpacked:
                # a range of names: NAME[2] is NAME0 and NAME1
                try:
                    names = [f"{member.name}{number}" for number in range(self.dims(member.dim_unpacked))]
                except Unknown:
                    last = None
                    continue
            for number, name in enumerate(names):
                num: Num | Unknown
                try:
                    if member.value and not number:
                        last = self._integer(self.evaluate(member.value))
                    elif last is None:
                        raise Unknown("the value of the member in front is not known")
                    else:
                        last += 1
                    num = Num(last)
                except Unknown as exc:
                    last = None
                    num = exc
                members.setdefault(name, num)

    @staticmethod
    def _integer(num: Num) -> int:
        if isinstance(num.value, bool) or not isinstance(num.value, int):
            raise Unknown("value is no integer")
        return num.value

    # --- number of bits ---

    def bits(self, text: str) -> int:
        """Number of bits of the type or name `text`: the result of `$bits(text)`. Raises `Unknown`."""
        return self.type_bits(text)

    def type_bits(self, text: str, dims: str = "") -> int:
        """Number of bits of the type `text` with the dimensions `dims`. Raises `Unknown`."""
        bits = self._vhdl_bits(text, bool(dims)) if self.lang == "vhdl" else self._sv_bits(text)
        return bits * self.dims(dims)

    def _sv_bits(self, text: str) -> int:
        mat = _RE_SV_TYPE.match(text)
        words = [word for word in (mat.group("name") if mat else text).split() if word not in _SV_QUALIFIERS]
        if mat is None or len(words) > 1:
            raise Unknown(f"the number of bits of '{' '.join(text.split())}' is not known")
        name = words[0] if words else "logic"
        dims = self.dims(mat.group("dims").strip())
        if name in _SV_BITS:
            return _SV_BITS[name] * dims
        return self._named_bits(name) * dims

    def _named_bits(self, name: str) -> int:
        """Number of bits of the user-defined type, type parameter, port or signal `name`."""
        scope, key = self, self.key(name)
        if "::" in name:
            package_name, _, type_name = name.rpartition("::")
            package = self.elab.package(package_name.rpartition("::")[2], self.lang)
            if package is None:
                raise Unknown(f"package '{package_name}' is not defined in the project")
            scope, key = package, package.key(type_name)
        elif "." in name:
            raise Unknown(f"the number of bits of the interface '{name}' is not known")
        for candidate in (scope, *(package for package, _ in scope.imports() if scope is self)):
            candidate_key = candidate.key(name.rpartition("::")[2])
            if candidate_key in candidate.typedefs:
                return candidate.typedef_bits(candidate.typedefs[candidate_key])
        if key in scope.params:
            return scope._param_bits(key, name)
        for unit in scope.units:
            for item in (*getattr(unit, "ports", ()), *getattr(unit, "signals", ())):
                if scope.key(item.name) == key:
                    return scope.item_bits(item)
        raise Unknown(f"the number of bits of '{name}' is not known")

    def _param_bits(self, key: str, name: str) -> int:
        param = self.params[key]
        num = self.param(key)
        if param.ptype == "type":
            if isinstance(num, Unknown) or not isinstance(num.value, str):
                raise Unknown(f"type '{name}' is not known")
            # the type is given by the instance: it is evaluated there
            scope = self.elab.parent_of(self) if key in self.overrides else self
            return (scope or self).type_bits(num.value)
        if not isinstance(num, Unknown) and num.width is not None:
            return num.width
        return self.type_bits(param.ptype or "int", param.dim) * self.dims(param.dim_unpacked)

    def typedef_bits(self, typedef: dm.Typedef) -> int:
        """Number of bits of the type `typedef`, which is declared by this scope. Raises `Unknown`."""
        if typedef.kind in ("struct", "union"):
            sizes = [
                self.type_bits(member.dtype or "logic", member.dim) * self.dims(member.dim_unpacked)
                for member in typedef.members
            ]
            if not sizes:
                raise Unknown(f"type '{typedef.name}' has no fields")
            return max(sizes) if typedef.kind == "union" else sum(sizes)
        if typedef.kind == "enum":
            if self.lang == "vhdl":
                raise Unknown(f"enumeration '{typedef.name}' has no number of bits")
            return self.type_bits(typedef.dtype or "int", typedef.dim)
        if self.lang == "vhdl":
            return self._vhdl_bits(typedef.dtype, False)
        return self.type_bits(typedef.dtype or "logic", typedef.dim) * self.dims(typedef.dim_unpacked)

    def _vhdl_bits(self, text: str, constrained: bool) -> int:
        """Number of bits of the VHDL type `text`. `constrained`: its range is given as dimension."""
        mat = _RE_VHDL_ARRAY.match(text.strip())
        if mat:
            return self._vhdl_range(mat.group("range")) * self._vhdl_bits(mat.group("type"), False)
        mat = _RE_VHDL_TYPE.match(text.strip())
        if mat is None:
            raise Unknown(f"the number of bits of '{' '.join(text.split())}' is not known")
        name = mat.group("name").lower().rpartition(".")[2]
        count = 1
        if mat.group("range") is not None:
            count, constrained = self._vhdl_range(mat.group("range")), True
        if name in _VHDL_BITS:
            return count
        if name in _VHDL_VECTORS:
            if not constrained:
                raise Unknown(f"'{name}' has no range")
            return count
        for candidate in (self, *(package for package, _ in self.imports())):
            if name in candidate.typedefs:
                return count * candidate.typedef_bits(candidate.typedefs[name])
        raise Unknown(f"the number of bits of '{name}' is not known")

    def _vhdl_range(self, text: str) -> int:
        """Number of elements of the range `left downto right` or `left to right`."""
        limits = _RE_VHDL_RANGE.split(text)
        if len(limits) != 2 or "," in text:  # noqa: PLR2004
            raise Unknown(f"the range '{' '.join(text.split())}' is not known")
        left, right = (self._integer(self.evaluate(limit)) for limit in limits)
        return abs(left - right) + 1

    def item_bits(self, item: dm.Port | dm.Signal) -> int:
        """Number of bits of the port or signal `item`. Raises `Unknown`."""
        if self.lang == "vhdl":
            return self.type_bits(item.dtype, item.dim)
        if "." in item.ptype or item.ptype == "interface":
            raise Unknown(f"'{item.ptype}' is an interface")
        return self.type_bits(item.ptype or "logic", item.dim) * self.dims(item.dim_unpacked)

    def all_ports(self) -> dict[str, dm.Value]:
        """Number of bits of all ports, by name."""
        ports: dict[str, dm.Value] = {}
        for unit in self.units:
            for port in getattr(unit, "ports", ()):
                expr = " ".join(filter(None, (port.ptype, port.dtype, port.dim, port.dim_unpacked)))
                try:
                    ports[port.name] = dm.Value(expr=expr, value=self.item_bits(port))
                except Unknown as exc:
                    ports[port.name] = dm.Value(expr=expr, unknown=str(exc))
        return ports


class Elaboration:
    """Values Of The Parameters Of A Project, Per Instance."""

    def __init__(self, project: "Project"):
        self.project = project
        self.packages: dict[tuple[str, bool], Scope | None] = {}
        self.parents: dict[int, Scope] = {}

    def package(self, name: str, lang: str) -> Scope | None:
        """Scope of the package `name`, used by code in language `lang`. `None` if it is not defined."""
        key = (name, lang == "vhdl")
        if key not in self.packages:
            definition = self.project.resolve_package(name, casefold=lang == "vhdl")
            self.packages[key] = Scope(self, definition) if definition else None
        return self.packages[key]

    def parent_of(self, scope: Scope) -> Scope | None:
        """Scope of the module, which instantiates `scope`."""
        return self.parents.get(id(scope))

    def scope(self, definition: "Definition", overrides: Mapping[str, dm.Value] | None = None) -> Scope:
        """Scope of an instance of the module `definition`, with the parameter values `overrides`."""
        return Scope(self, definition, overrides)

    def overrides(self, parent: Scope, inst: dm.ModuleInstance, lang: str, child: "Definition") -> dict[str, dm.Value]:
        """Values of the parameters of `child`, given by the instance `inst` within `parent`."""
        declared = list(child.unit.params)
        names = {param.name.lower() if child.file.lang == "vhdl" else param.name: param for param in declared}
        overrides: dict[str, dm.Value] = {}
        position = 0
        for con in inst.params:
            if con.port:
                param = names.get(con.port.lower() if child.file.lang == "vhdl" else con.port)
            else:
                param = declared[position] if position < len(declared) else None
                position += 1
            if param is None or not con.con:
                continue
            if param.ptype == "type":
                overrides[param.name] = dm.Value(expr=con.con, value=" ".join(con.con.split()))
            else:
                overrides[param.name] = parent.value_of(con.con, lang)
        return overrides

    def top_scope(self, definition: "Definition", overrides: Mapping[str, dm.Value]) -> Scope:
        """Scope of the top `definition`, with the parameter values `overrides` given by the user.

        Raises `ValueError` for a name which is no parameter of `definition`.
        """
        scope = Scope(self, definition, overrides)
        declared = {scope.key(param.name) for unit in scope.units for param in unit.params}
        unknown = sorted(name for name in overrides if scope.key(name) not in declared)
        if unknown:
            valid = sorted(param.name for param in definition.unit.params)
            raise ValueError(
                f"'{definition.unit.name}' has no parameter {', '.join(repr(name) for name in unknown)}. "
                f"Parameters: {', '.join(valid) or 'none'}."
            )
        return scope

    def top_overrides(self, params: Mapping[str, Scalar] | None) -> dict[str, dm.Value]:
        """Values of the parameters of the top, as given."""
        return {name: dm.Value(expr=str(value), value=value) for name, value in (params or {}).items()}
