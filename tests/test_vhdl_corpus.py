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

"""Snapshot And Invariant Tests Over A Corpus Of Real World VHDL."""

import re
from pathlib import Path

from pytest import mark
from test2ref import assert_refdata

from hdl_parser import File, Module, ModuleInstance, Port, parse_file
from hdl_parser._vhdl.tokenizer import KEYWORDS
from hdl_parser.datamodel import Connection

from .conftest import EXAMPLES

CORPUS_PATH = Path(__file__).parent / "corpus" / "vhdl"
CORPUS = tuple(sorted(CORPUS_PATH.glob("*/*.vhd*"), key=lambda path: path.relative_to(CORPUS_PATH).as_posix()))
VHDL_EXAMPLES = tuple(path for path in EXAMPLES if path.suffix in (".vhd", ".vhdl"))

_MODES = ("in", "out", "inout", "buffer", "linkage")
_NAME = re.compile(r"[a-zA-Z]\w*\Z")
# Comments and strings may contain anything
_NO_CODE = re.compile(r'--[^\n]*|/\*.*?\*/|"(?:[^"\n]|"")*"', re.DOTALL)
_ENTITY = re.compile(r"\bentity\s+(\w+)\s+is\b", re.IGNORECASE)
_ARCHITECTURE = re.compile(r"\barchitecture\s+\w+\s+of\s+(\w+)", re.IGNORECASE)
_PORT_MAP = re.compile(r"\bport\s+map\b", re.IGNORECASE)
_PAIRS = {")": "(", "]": "[", "}": "{"}


def _is_balanced(text: str) -> bool:
    stack = []
    for char in re.sub(r"'.'", "", _NO_CODE.sub("", text)):
        if char in "([{":
            stack.append(char)
        elif char in _PAIRS and (not stack or stack.pop() != _PAIRS[char]):
            return False
    return not stack


def _check_name(errors: list[str], where: str, name: str, code: str) -> None:
    if not _NAME.match(name):
        errors.append(f"{where}: invalid name")
    elif name.lower() in KEYWORDS:
        errors.append(f"{where}: name is a keyword")
    elif not re.search(rf"\b{name}\b", code):
        errors.append(f"{where}: name not found in source")


def _check_module(errors: list[str], mod: Module, code: str) -> None:  # noqa: C901
    _check_name(errors, f"module {mod.name!r}", mod.name, code)
    for kind, decls in (("param", mod.params), ("port", mod.ports)):
        names = [decl.name.lower() for decl in decls]
        errors += [f"{mod.name}: duplicate {kind} {name!r}" for name in sorted(set(names)) if names.count(name) > 1]
    for param in mod.params:
        where = f"{mod.name}: param {param.name!r}"
        _check_name(errors, where, param.name, code)
        if not _is_balanced(param.dim) or not _is_balanced(param.default):
            errors.append(f"{where}: unbalanced dimension or default")
    for port in mod.ports:
        where = f"{mod.name}: port {port.name!r}"
        _check_name(errors, where, port.name, code)
        if port.direction not in _MODES:
            errors.append(f"{where}: invalid direction {port.direction!r}")
        if not port.dtype:
            errors.append(f"{where}: no type")
        if not _is_balanced(port.dim):
            errors.append(f"{where}: unbalanced dimension")
    for inst in mod.insts:
        where = f"{mod.name}: instance {inst.name!r}"
        _check_name(errors, where, inst.name, code)
        _check_name(errors, f"{where} of {inst.module!r}", inst.module, code)
        for con in inst.connections:
            if not con.con or not _is_balanced(con.port) or not _is_balanced(con.con):
                errors.append(f"{where}: empty or unbalanced connection {con.port!r} => {con.con!r}")


def check_invariants(file: File, text: str) -> list[str]:
    """Check `file`, the parser result of `text`, for things which are always wrong."""
    errors: list[str] = []
    code = _NO_CODE.sub(" ", text)
    for mod in file.modules:
        _check_module(errors, mod, code)
    # an independent count of what is to be found
    names = {name.lower() for name in _ENTITY.findall(code) + _ARCHITECTURE.findall(code)}
    if names != {mod.name.lower() for mod in file.modules}:
        errors.append(f"parsed modules {[mod.name for mod in file.modules]}, but source declares {sorted(names)}")
    connected = sum(1 for mod in file.modules for inst in mod.insts if inst.connections)
    port_maps = len(_PORT_MAP.findall(code))
    if connected != port_maps:
        errors.append(f"parsed {connected} instances with connections, but source has {port_maps} port maps")
    return errors


@mark.parametrize("path", CORPUS, ids=lambda path: path.relative_to(CORPUS_PATH).as_posix())
def test_corpus_snapshot(tmp_path, path):
    """Parse Corpus File And Compare With 'refdata'."""
    flavor = path.relative_to(CORPUS_PATH).as_posix().replace("/", "-")
    file = parse_file(path)
    (tmp_path / "overview.json").write_text(file.overview)
    assert_refdata(test_corpus_snapshot, tmp_path, flavor=flavor)


@mark.parametrize("path", CORPUS, ids=lambda path: path.relative_to(CORPUS_PATH).as_posix())
def test_corpus_invariants(path):
    """Check Invariants On Corpus File."""
    assert check_invariants(parse_file(path), path.read_text()) == []


@mark.parametrize("path", VHDL_EXAMPLES, ids=lambda path: path.name)
def test_examples_invariants(path):
    """Check Invariants On Examples."""
    assert check_invariants(parse_file(path), path.read_text()) == []


def _file(**kwargs) -> File:
    return File(path=None, modules=(Module(name="top", **kwargs),))


def test_checker_ok():
    """Valid Result Passes."""
    file = _file(ports=(Port(direction="in", dtype="std_logic_vector", name="a_i", dim="[3:0]"),))
    assert check_invariants(file, "entity top is port (a_i : in std_logic_vector(3 downto 0)); end;") == []


def test_checker_ports():
    """Bad Names, Directions, Types And Dimensions Are Found."""
    ports = (
        Port(direction="input", dtype="std_logic", name="signal"),
        Port(direction="in", name="ghost", dim="[3:0"),
        Port(direction="in", dtype="std_logic", name="a"),
        Port(direction="in", dtype="std_logic", name="A"),
        Port(direction="in", dtype="std_logic", name="1a"),
    )
    errors = check_invariants(_file(ports=ports), "entity top is port (a : in std_logic); end; -- ghost")
    assert any("'signal': name is a keyword" in err for err in errors)
    assert any("invalid direction 'input'" in err for err in errors)
    assert any("'ghost': name not found" in err for err in errors)
    assert any("'ghost': no type" in err for err in errors)
    assert any("'ghost': unbalanced dimension" in err for err in errors)
    assert any("duplicate port 'a'" in err for err in errors)
    assert any("'1a': invalid name" in err for err in errors)


def test_checker_instances():
    """Bad Connections And Count Mismatches Are Found."""
    insts = (
        ModuleInstance(name="u0", module="sub", connections=(Connection(port="a", con="f(x"),)),
        ModuleInstance(name="u1", module="sub", connections=(Connection(port="a", con=""),)),
    )
    text = """
        entity top is end;
        architecture rtl of top is begin
            u0 : sub port map (a => f(x));
            u1 : sub port map (a => ')');
            u2 : sub port map (a => a);
        end;
        entity other is end;
        """
    errors = check_invariants(_file(insts=insts), text)
    assert any("'u0': empty or unbalanced connection" in err for err in errors)
    assert any("'u1': empty or unbalanced connection" in err for err in errors)
    assert any("but source declares ['other', 'top']" in err for err in errors)
    assert any("parsed 2 instances with connections, but source has 3 port maps" in err for err in errors)
