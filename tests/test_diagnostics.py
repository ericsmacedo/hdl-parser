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

"""Diagnostics."""

import logging

from pytest import mark

from hdl_parser import Diagnostic, Location, parse_file, parse_text
from hdl_parser._diagnostics import SEVERITIES

from .conftest import PRJ_PATH

CORPUS = tuple(
    sorted(
        path for path in (PRJ_PATH / "tests" / "corpus").rglob("*.*") if path.suffix in (".sv", ".v", ".vhd", ".vhdl")
    )
)


def _codes(file) -> list[str]:
    return [diag.code for diag in file.diagnostics]


def _text_at(text: str, loc: Location) -> str:
    """Source text at `loc` (single line)."""
    assert loc.line == loc.end_line
    return text.split("\n")[loc.line - 1][loc.col - 1 : loc.end_col - 1]


def test_clean():
    """No Problem, No Diagnostic."""
    file = parse_text("module top (input a); endmodule")
    assert file.diagnostics == ()
    assert '"diagnostics"' not in file.overview


def test_no_module(caplog):
    """A File Without Module Is An Information."""
    with caplog.at_level(logging.INFO):
        file = parse_text("package p; endpackage", file_path="p.sv")
    assert file.diagnostics == (Diagnostic(code="no-module", severity="info", message="no module found."),)
    assert "INFO" in caplog.text
    assert "p.sv: no module found." in caplog.text


def test_macro_not_expanded(caplog):
    """Macro In The Module Header Is Related To Its Macro Call."""
    text = "module top (\n  `PORTS(a)\n);\nendmodule\n"
    file = parse_text(text, file_path="top.sv")
    (diag,) = file.diagnostics
    assert diag.code == "macro-not-expanded"
    assert diag.severity == "warning"
    assert diag.loc == Location(line=2, col=3, end_line=2, end_col=12)
    assert diag.item == "top.`PORTS"
    assert file.find(diag.item) is file.modules[0].unresolved_macros[0]
    assert "WARNING" in caplog.text
    assert "top.sv:2:3: module 'top': macro `PORTS in module header is not expanded." in caplog.text
    assert '"diagnostics"' in file.overview


@mark.parametrize(
    "code, defines, use",
    (
        ("macro-recursive", "`define A `B\n`define B `A\n", "`A"),
        ("macro-args-missing", "`define P(n) input n\n", "`P"),
        ("macro-args-count", "`define P(n) input n\n", "`P(a, b)"),
        ("macro-ambiguous", "`ifdef X\n`define P input a\n`else\n`define P input b\n`endif\n", "`P"),
    ),
)
def test_macro_use(code, defines, use):
    """Macros Which Cannot Be Expanded Point To Their Use."""
    text = f"{defines}module top (\n  {use}\n);\nendmodule\n"
    file = parse_text(text, expand_macros=True)
    diag = file.diagnostics[0]
    assert diag.code == code
    assert _text_at(text, diag.loc) == use.partition("(")[0]
    # located within module 'top'
    assert diag.item == "top"
    # the macro is still there
    assert _codes(file)[1:] == ["macro-not-expanded"]


def test_macro_within_macro():
    """A Problem Within A Macro Points To The Outermost Macro Call."""
    text = "`define INNER(a) input a\n`define OUTER `INNER\nmodule top (\n  `OUTER\n);\nendmodule\n"
    diag = parse_text(text, expand_macros=True).diagnostics[0]
    assert diag.code == "macro-args-missing"
    assert _text_at(text, diag.loc) == "`OUTER"


def test_macro_bad_define():
    """Definition Which Cannot Be Parsed."""
    text = "`define P(a input a\nmodule top; endmodule\n"
    (diag,) = parse_text(text, expand_macros=True).diagnostics
    assert diag.code == "macro-bad-define"
    assert diag.loc.line == 1
    assert diag.item == ""


def test_include(tmp_path, caplog):
    """Missing Include, And A Problem Within An Included File."""
    (tmp_path / "defs.svh").write_text('`define P(a input a\n`include "deeper.svh"\n')
    text = '`include "defs.svh"\n`include "missing.svh"\nmodule top; endmodule\n'
    path = tmp_path / "top.sv"
    path.write_text(text)
    file = parse_file(path, expand_macros=True)
    assert _codes(file) == ["macro-bad-define", "include-not-found", "include-not-found"]
    bad, deeper, missing = file.diagnostics
    # problems of the included file point to the include statement
    assert _text_at(text, bad.loc) == '`include "defs.svh"'
    assert bad.file == deeper.file == str(tmp_path / "defs.svh")
    assert "deeper.svh" in deeper.message
    assert _text_at(text, missing.loc) == '`include "missing.svh"'
    assert missing.file == ""
    assert f"{path}:1:1: {tmp_path / 'defs.svh'}: cannot parse definition of macro `P." in caplog.text
    assert f"{path}:2:1: included file 'missing.svh' not found." in caplog.text


def test_include_unreadable(tmp_path):
    """Included File Which Cannot Be Read."""
    (tmp_path / "defs.svh").write_bytes(b"\xff")
    (tmp_path / "defs.svh").chmod(0)
    path = tmp_path / "top.sv"
    path.write_text('`include "defs.svh"\nmodule top; endmodule\n')
    file = parse_file(path, expand_macros=True)
    (tmp_path / "defs.svh").chmod(0o644)
    # root may read anything
    assert _codes(file) in ([], ["include-unreadable"])


def test_header_item_skipped():
    """Code Within The Module Header, Which Is Not Understood."""
    text = "module top #(parameter A = 1) (\n  input a,\n  + - 3,\n  input b\n);\nendmodule\n"
    file = parse_text(text)
    (diag,) = file.diagnostics
    assert diag.code == "header-item-skipped"
    assert _text_at(text, diag.loc) == "+ - 3"
    assert "'+ - 3'" in diag.message
    assert diag.item == "top"
    assert [port.name for port in file.modules[0].ports] == ["a", "b"]


def test_missing_end():
    """Module Without `endmodule`."""
    text = "module one (input a);\nmodule two (input b);\nendmodule\n"
    file = parse_text(text)
    (diag,) = file.diagnostics
    assert diag.code == "missing-end"
    assert _text_at(text, diag.loc) == "module one"
    assert diag.item == "one"


def test_unbalanced_bracket():
    """Brackets Which Are Never Closed."""
    # the port list takes the module body
    text = "module top (input a;\n  assign x = (a;\nendmodule\n"
    file = parse_text(text)
    assert _codes(file) == ["unbalanced-bracket", "header-item-skipped", "unbalanced-bracket"]
    assert file.diagnostics[0].loc == Location(line=1, col=12, end_line=1, end_col=13)
    text = "module top (input a);\n  sub u0 (.a(a);\n  assign x = (a;\nendmodule\n"
    file = parse_text(text)
    assert [(diag.code, diag.loc.line, diag.loc.col) for diag in file.diagnostics] == [
        ("unbalanced-bracket", 2, 10),
        ("unbalanced-bracket", 3, 14),
    ]


def test_vhdl():
    """VHDL Problems."""
    text = """\
entity top is
  generic (type T; W : natural);
  port (a : in bit);
end;
architecture rtl of top is
begin
  u0 : entity work.sub port map (a => a;
"""
    file = parse_text(text, lang="vhdl")
    assert [(diag.code, diag.loc.line, diag.item) for diag in file.diagnostics] == [
        ("header-item-skipped", 2, "top"),
        ("missing-end", 5, ""),
        ("unbalanced-bracket", 7, ""),
    ]
    assert "'type T'" in file.diagnostics[0].message
    assert "architecture 'top' has no 'end'" in file.diagnostics[1].message
    assert [param.name for param in file.modules[0].params] == ["W"]
    text = "entity top is\n  port (a : in bit);\n"
    assert _codes(parse_text(text, lang="vhdl")) == ["missing-end"]


def test_order():
    """Diagnostics Are Sorted By Location."""
    text = "module one (\n  `A\n);\nendmodule\nmodule two (\n  input a,\n  1 2\n);\n"
    file = parse_text(text)
    assert [(diag.code, diag.loc.line, diag.item) for diag in file.diagnostics] == [
        ("macro-not-expanded", 2, "one.`A"),
        ("missing-end", 5, "two"),
        ("header-item-skipped", 7, "two"),
    ]


def test_codes_documented():
    """Every Code Is Documented With Its Severity."""
    doc = Diagnostic.__doc__
    for code, severity in SEVERITIES.items():
        assert any(f"`{code}`" in line and f"| {severity} " in line for line in doc.splitlines()), code


@mark.parametrize("path", CORPUS, ids=lambda path: str(path.relative_to(PRJ_PATH / "tests" / "corpus")))
def test_corpus(path):
    """Real Code Parses Without Parser Problems. Diagnostics Have A Known Code And Point Into The File."""
    allowed = {"no-module", "macro-not-expanded", "include-not-found"}
    lines = path.read_bytes().count(b"\n") + 1
    for kwargs in ({}, {"expand_macros": True}):
        if kwargs and path.suffix not in (".sv", ".v"):
            continue
        for diag in parse_file(path, **kwargs).diagnostics:
            assert diag.code in allowed, diag
            assert diag.severity == SEVERITIES[diag.code]
            assert diag.loc is None or diag.loc.end_line <= lines
