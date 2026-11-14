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

from difflib import unified_diff
from pathlib import Path

from pytest import mark, param
from test2ref import assert_refdata

from hdl_parser import File, Module, ModuleInstance, Port, parse_defines_text, parse_file
from hdl_parser._sv.preproc import expand
from hdl_parser.datamodel import Connection

from .conftest import EXAMPLES
from .sv_invariants import check_invariants

CORPUS_PATH = Path(__file__).parent / "corpus" / "sv"
CORPUS = tuple(sorted(CORPUS_PATH.glob("*/*.sv"), key=lambda path: path.relative_to(CORPUS_PATH).as_posix()))
SV_EXAMPLES = tuple(path for path in EXAMPLES if path.suffix == ".sv")

# Relative path (posix) -> reason. Entries are expected to fail; once the bug is fixed, the strict xfail flips the
# test to failing (XPASS) and the entry has to be removed.
_NO_MODULE = "package-only file raises RuntimeError('No module found.')"
KNOWN_ISSUES_SNAPSHOT: dict[str, str] = {"ibex/ibex_pkg.sv": _NO_MODULE}
KNOWN_ISSUES_INVARIANTS: dict[str, str] = {"ibex/ibex_pkg.sv": _NO_MODULE}
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


# --- macro expansion ---

# Defines of a typical synthesis flow
FLOW_MACROS = parse_defines_text("`define SYNTHESIS\n`define RVFI\n`define INC_ASSERT\n")


_NOT_COMPILED = frozenset(f"!{name}" for name in FLOW_MACROS)
_RESOLVED = _NOT_COMPILED.union(FLOW_MACROS)


def _inc_dirs(path: Path) -> tuple[Path, ...]:
    """Include Directories: The Ones Of The Project First."""
    return (path.parent / "include", CORPUS_PATH, *sorted(CORPUS_PATH.glob("*/include")))


def _diff(path: Path, expanded: str) -> str:
    """Changes Made By The Preprocessor."""
    lines = unified_diff(path.read_text().splitlines(), expanded.splitlines(), "original", "expanded", lineterm="", n=0)
    return "".join(f"{line.rstrip()}\n" for line in lines)


@mark.parametrize("path", _cases(KNOWN_ISSUES_SNAPSHOT))
def test_corpus_expand(tmp_path, path):
    """Macro Expansion On The Corpus, With The Macro Files Of The Projects.

    None of the corpus files creates parameters, ports or instances by macros, so the result has to be the same
    as without macro expansion. The changes made by the preprocessor are compared with 'refdata'.
    """
    inc_dirs = _inc_dirs(path)
    file = parse_file(path, expand_macros=True, resolve_ifdefs=True, inc_dirs=inc_dirs)
    assert file == parse_file(path)

    source = path.read_text()
    expanded = expand(source, file_path=path, inc_dirs=inc_dirs, resolve_ifdefs=True)
    assert check_invariants(file, expanded) == []
    if expanded != source:
        flavor = path.relative_to(CORPUS_PATH).as_posix().replace("/", "-")
        (tmp_path / "expanded.diff").write_text(_diff(path, expanded))
        assert_refdata(test_corpus_expand, tmp_path, flavor=flavor)


@mark.parametrize("path", _cases(KNOWN_ISSUES_SNAPSHOT))
def test_corpus_resolve(tmp_path, path):
    """Resolution Of `ifdef On The Corpus, With The Defines Of A Synthesis Flow."""
    inc_dirs = _inc_dirs(path)
    file = parse_file(path, expand_macros=True, resolve_ifdefs=True, inc_dirs=inc_dirs, macros=FLOW_MACROS)
    default = parse_file(path)

    assert [module.name for module in file.modules] == [module.name for module in default.modules]
    for module, default_module in zip(file.modules, default.modules, strict=True):
        for name in ("params", "localparams", "ports", "insts"):
            items = getattr(module, name)
            default_items = getattr(default_module, name)
            # code which is not compiled is gone, nothing else
            assert [item.name for item in items] == [
                item.name for item in default_items if _NOT_COMPILED.isdisjoint(item.ifdefs)
            ]
            # the resolved conditions are gone
            assert all(_RESOLVED.isdisjoint(item.ifdefs) for item in items)

    source = path.read_text()
    expanded = expand(source, file_path=path, inc_dirs=inc_dirs, resolve_ifdefs=True, macros=FLOW_MACROS)
    assert check_invariants(file, expanded) == []
    if expanded != source:
        flavor = path.relative_to(CORPUS_PATH).as_posix().replace("/", "-")
        (tmp_path / "expanded.diff").write_text(_diff(path, expanded))
        assert_refdata(test_corpus_resolve, tmp_path, flavor=flavor)


def test_corpus_rvfi():
    """The Formal Interface Of Ibex Depends On A Define."""
    path = CORPUS_PATH / "ibex" / "ibex_top.sv"
    ports = parse_file(path).modules[0].ports
    rvfi = [port.name for port in ports if port.ifdefs == ("RVFI",)]
    assert len(rvfi) > 20
    kwargs = {"expand_macros": True, "resolve_ifdefs": True, "inc_dirs": _inc_dirs(path)}
    # not defined: nothing changes
    assert parse_file(path, **kwargs).modules[0].ports == ports
    # defined: no longer conditional
    macros = parse_defines_text("`define RVFI")
    resolved = parse_file(path, macros=macros, **kwargs).modules[0].ports
    assert [port.name for port in resolved] == [port.name for port in ports]
    assert all(port.ifdefs == () for port in resolved if port.name in rvfi)


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
