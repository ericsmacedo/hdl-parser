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

"""Structural Invariants Every Parse Result Must Fulfil."""

import re

from hdl_parser import File, Module
from hdl_parser._sv.lexer import keywords_types_tup

IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_$]*$")
IFDEF = re.compile(r"^!?[a-zA-Z_]\w*$")
DIRECTIONS = ("input", "output", "inout", "")
_KEYWORDS = frozenset(keywords_types_tup)
_PAIRS = {")": "(", "]": "[", "}": "{"}
_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
_COMMENT_OR_STRING = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"', re.DOTALL)
_MODULE_DECL = re.compile(r"\b(?:macro)?module\b")


def _balanced(text: str, closers: str = ")]}") -> bool:
    """Check Brackets Of `text` Are Balanced, Ignoring String Literals."""
    stack: list[str] = []
    for char in _STRING.sub("", text):
        if char in "([{":
            stack.append(char)
        elif char in closers:
            if not stack or stack.pop() != _PAIRS[char]:
                return False
    return not stack


def _check_name(kind: str, name: str, where: str) -> list[str]:
    if not IDENT.match(name):
        return [f"{where}: {kind} name {name!r} is not an identifier"]
    if name in _KEYWORDS:
        return [f"{where}: {kind} name {name!r} is a keyword or built-in type"]
    return []


def _check_dim(kind: str, dim: str, where: str) -> list[str]:
    if dim and not (dim.startswith("[") and dim.endswith("]") and _balanced(dim)):
        return [f"{where}: {kind} {dim!r} is not a bracketed, balanced dimension"]
    return []


def _check_ifdefs(ifdefs: tuple[str, ...], where: str) -> list[str]:
    return [f"{where}: invalid ifdef entry {entry!r}" for entry in ifdefs if not IFDEF.match(entry)]


def _check_module(mod: Module, source: str) -> list[str]:  # noqa: C901, PLR0912
    errors: list[str] = []
    where = f"module {mod.name!r}"
    errors += _check_name("module", mod.name, where)
    errors += _check_ifdefs(mod.ifdefs, where)
    for ports_kind, ports in (("port", mod.ports),):
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for port in ports:
            pwhere = f"{where} {ports_kind} {port.name!r}"
            errors += _check_name(ports_kind, port.name, where)
            if port.direction not in DIRECTIONS:
                errors.append(f"{pwhere}: invalid direction {port.direction!r}")
            if (port.name, port.ifdefs) in seen:
                errors.append(f"{pwhere}: duplicate (name, ifdefs)")
            seen.add((port.name, port.ifdefs))
            errors += _check_dim("dim", port.dim, pwhere)
            errors += _check_dim("dim_unpacked", port.dim_unpacked, pwhere)
            errors += _check_ifdefs(port.ifdefs, pwhere)
            if not re.search(rf"(?<![\w$]){re.escape(port.name)}(?![\w$])", source):
                errors.append(f"{pwhere}: name not found in source")
    for kind, params in (("param", mod.params), ("localparam", mod.localparams)):
        seen_params: set[tuple[str, tuple[str, ...]]] = set()
        for param in params:
            pwhere = f"{where} {kind} {param.name!r}"
            errors += _check_name(kind, param.name, where)
            if (param.name, param.ifdefs) in seen_params:
                errors.append(f"{pwhere}: duplicate (name, ifdefs)")
            seen_params.add((param.name, param.ifdefs))
            errors += _check_dim("dim", param.dim, pwhere)
            errors += _check_dim("dim_unpacked", param.dim_unpacked, pwhere)
            errors += _check_ifdefs(param.ifdefs, pwhere)
    for inst in mod.insts:
        iwhere = f"{where} instance {inst.name!r}"
        errors += _check_name("instance", inst.name, where)
        errors += _check_name("instance module", inst.module, iwhere)
        errors += _check_ifdefs(inst.ifdefs, iwhere)
        if not re.search(rf"(?<![\w$]){re.escape(inst.name)}(?![\w$])", source):
            errors.append(f"{iwhere}: name not found in source")
        for con in inst.connections:
            if con.port and not IDENT.match(con.port):
                errors.append(f"{iwhere}: connection port {con.port!r} is not an identifier")
            if not _balanced(con.con):
                errors.append(f"{iwhere}: connection {con.port!r} has unbalanced brackets: {con.con!r}")
            errors += _check_ifdefs(con.ifdefs, iwhere)
    for macro in mod.unresolved_macros:
        errors += _check_ifdefs(macro.ifdefs, f"{where} macro {macro.name!r}")
    return errors


def _count_modules(source: str) -> int:
    stripped = _COMMENT_OR_STRING.sub(" ", source)
    return len(_MODULE_DECL.findall(stripped))


def check_invariants(file: File, source: str) -> list[str]:
    """Check Structural Invariants of a Parse Result.

    Args:
        file: Parse result.
        source: Text of the parsed source file.

    Returns:
        Human readable violations. Empty if everything is fine.
    """
    errors: list[str] = []
    for mod in file.modules:
        errors += _check_module(mod, source)
    expected = _count_modules(source)
    if len(file.modules) != expected:
        errors.append(f"parsed {len(file.modules)} modules, but source declares {expected}")
    return errors
