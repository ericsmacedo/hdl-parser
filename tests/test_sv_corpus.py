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

"""Snapshot And Invariant Tests Over A Corpus Of Real World SystemVerilog."""

from pathlib import Path

from pytest import mark, param
from test2ref import assert_refdata

from hdl_parser import File, Module, ModuleInstance, Port, parse_file
from hdl_parser.datamodel import Connection

from .conftest import EXAMPLES
from .sv_invariants import check_invariants

CORPUS_PATH = Path(__file__).parent / "corpus" / "sv"
CORPUS = tuple(sorted(CORPUS_PATH.glob("*/*.sv"), key=lambda path: path.relative_to(CORPUS_PATH).as_posix()))
SV_EXAMPLES = tuple(path for path in EXAMPLES if path.suffix == ".sv")

# Relative path (posix) -> reason. Entries are expected to fail; once the bug is fixed, the strict xfail flips the
# test to failing (XPASS) and the entry has to be removed.
KNOWN_ISSUES_SNAPSHOT: dict[str, str] = {}
KNOWN_ISSUES_INVARIANTS: dict[str, str] = {}
# Union, as documentation and for the report.
KNOWN_ISSUES: dict[str, str] = {**KNOWN_ISSUES_SNAPSHOT, **KNOWN_ISSUES_INVARIANTS}


def _cases(issues: dict[str, str]) -> list:
    cases = []
    for path in CORPUS:
        rel = path.relative_to(CORPUS_PATH).as_posix()
        marks = []
        if rel in issues:
            marks.append(mark.xfail(strict=True, reason=issues[rel]))
        cases.append(param(path, id=rel, marks=marks))
    return cases


@mark.parametrize("path", _cases(KNOWN_ISSUES_SNAPSHOT))
def test_corpus_snapshot(tmp_path, path):
    """Parse Corpus File And Compare With 'refdata'."""
    flavor = path.relative_to(CORPUS_PATH).as_posix().replace("/", "-")
    file = parse_file(path)
    (tmp_path / "overview.json").write_text(file.overview)
    assert_refdata(test_corpus_snapshot, tmp_path, flavor=flavor)


@mark.parametrize("path", _cases(KNOWN_ISSUES_INVARIANTS))
def test_corpus_invariants(path):
    """Check Invariants On Corpus File."""
    file = parse_file(path)
    assert check_invariants(file, path.read_text()) == []


@mark.parametrize("path", SV_EXAMPLES, ids=lambda path: path.name)
def test_examples_invariants(path):
    """Check Invariants On Examples."""
    file = parse_file(path)
    assert check_invariants(file, path.read_text()) == []


def _mod(**kwargs) -> File:
    return File(path=None, modules=(Module(name=kwargs.pop("name", "top"), **kwargs),))


def test_checker_ok():
    """Valid Result Passes."""
    file = _mod(ports=(Port(direction="input", name="a_i", dim="[3:0]"),))
    assert check_invariants(file, "module top(input [3:0] a_i); endmodule") == []


def test_checker_bad_port_name():
    """Keyword Port Name, Bad Direction And Missing Source Occurrence Are Found."""
    file = _mod(ports=(Port(direction="in", name="logic"), Port(name="ghost")))
    errors = check_invariants(file, "module top(input logic x); endmodule")
    assert any("keyword" in err for err in errors)
    assert any("invalid direction" in err for err in errors)
    assert any("'ghost': name not found" in err for err in errors)


def test_checker_duplicates_and_dim():
    """Duplicate Ports And Unbalanced Dimensions Are Found."""
    file = _mod(ports=(Port(name="a", dim="[3:0"), Port(name="a")))
    errors = check_invariants(file, "module top(a); endmodule")
    assert any("duplicate" in err for err in errors)
    assert any("dimension" in err for err in errors)


def test_checker_connection_and_ifdef():
    """Unbalanced Connections, Bad Ifdefs And Module Count Mismatch Are Found."""
    inst = ModuleInstance(name="u", module="sub", connections=(Connection(port="e", con="f(x"),), ifdefs=("1bad",))
    file = _mod(insts=(inst,))
    errors = check_invariants(
        file, 'module top; sub u(.e(f(x)); // module "module"\nendmodule\nmodule other; endmodule'
    )
    assert any("unbalanced" in err for err in errors)
    assert any("invalid ifdef" in err for err in errors)
    assert any("parsed 1 modules, but source declares 2" in err for err in errors)
