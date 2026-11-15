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

"""Packages And Types."""

from hdl_parser import Location, Member, Package, Param, Typedef, parse_file, parse_text

from .conftest import PRJ_PATH, plain

TEXT = """\
// Bus types
package bus_pkg;
  import other_pkg::*;
  localparam int AW = 32;
  parameter P = 1;
  // State of the bus
  typedef enum logic [1:0] {
    IDLE,      // nothing to do
    BUSY = 2,  // working
    ERR[2]
  } state_t;
  typedef struct packed {
    logic [AW-1:0] addr; // address
    logic          we, re;
    other_pkg::x_t [1:0] x [4];
    int signed     n = 3;
  } req_t;
  typedef union { int i; real r; } num_t;
  typedef logic [7:0] byte_t;
  typedef byte_t word_t [4];
  typedef enum {A, B} plain_e;
  function automatic int f(int a); typedef int inner_t; return a; endfunction
  typedef req_t resp_t;
endpackage : bus_pkg
"""


def _text_at(text: str, loc: Location) -> str:
    """Source text at `loc`."""
    lines = text.split("\n")[loc.line - 1 : loc.end_line]
    lines[-1] = lines[-1][: loc.end_col - 1]
    lines[0] = lines[0][loc.col - 1 :]
    return "\n".join(lines)


def test_package():
    """Package With Parameters And Types."""
    file = parse_text(TEXT)
    assert file.modules == ()
    assert file.diagnostics == ()
    (package,) = file.packages
    assert plain(package) == Package(
        name="bus_pkg",
        params=(Param(name="P", default="1"),),
        localparams=(Param(ptype="int", name="AW", default="32"),),
        typedefs=(
            Typedef(
                name="state_t",
                kind="enum",
                dtype="logic",
                dim="[1:0]",
                members=(
                    Member(name="IDLE", comment=("nothing to do",)),
                    Member(name="BUSY", value="2", comment=("working",)),
                    Member(name="ERR", dim_unpacked="[2]"),
                ),
                comment=("State of the bus",),
            ),
            Typedef(
                name="req_t",
                kind="struct",
                dtype="packed",
                members=(
                    Member(name="addr", dtype="logic", dim="[AW-1:0]", comment=("address",)),
                    Member(name="we", dtype="logic"),
                    Member(name="re", dtype="logic"),
                    Member(name="x", dtype="other_pkg::x_t", dim="[1:0]", dim_unpacked="[4]"),
                    Member(name="n", dtype="int signed", value="3"),
                ),
            ),
            Typedef(
                name="num_t", kind="union", members=(Member(name="i", dtype="int"), Member(name="r", dtype="real"))
            ),
            Typedef(name="byte_t", kind="alias", dtype="logic", dim="[7:0]"),
            Typedef(name="word_t", kind="alias", dtype="byte_t", dim_unpacked="[4]"),
            Typedef(name="plain_e", kind="enum", members=(Member(name="A"), Member(name="B"))),
            # types within functions are local
            Typedef(name="resp_t", kind="alias", dtype="req_t"),
        ),
    )


def test_ids_and_locations():
    """Identifiers And Source Locations."""
    file = parse_text(TEXT)
    package = file.packages[0]
    assert [item.id for item in file.iter_items()][:9] == [
        "bus_pkg",
        "bus_pkg.P",
        "bus_pkg.AW",
        "bus_pkg.state_t",
        "bus_pkg.state_t.IDLE",
        "bus_pkg.state_t.BUSY",
        "bus_pkg.state_t.ERR",
        "bus_pkg.req_t",
        "bus_pkg.req_t.addr",
    ]
    assert _text_at(TEXT, package.loc).startswith("package bus_pkg;")
    assert _text_at(TEXT, package.loc).endswith("endpackage : bus_pkg")
    state = file.find("bus_pkg.state_t")
    assert _text_at(TEXT, state.loc).startswith("typedef enum logic [1:0] {")
    assert _text_at(TEXT, state.loc).endswith("} state_t;")
    assert _text_at(TEXT, file.find("bus_pkg.state_t.BUSY").loc) == "BUSY = 2"
    assert _text_at(TEXT, file.find("bus_pkg.req_t.re").loc) == "logic          we, re"
    assert _text_at(TEXT, file.find("bus_pkg.byte_t").loc) == "typedef logic [7:0] byte_t;"
    assert '"packages"' in file.overview


def test_forward_declarations():
    """Forward Declarations Are No Types."""
    text = "package p;\n  typedef fwd_t;\n  typedef class c;\n  typedef enum e;\n  typedef int i_t;\nendpackage\n"
    assert [typedef.name for typedef in parse_text(text).packages[0].typedefs] == ["i_t"]


def test_module_typedefs():
    """Types Declared Within A Module, Next To A Package."""
    text = """\
package p; typedef logic t; endpackage
module top (input p::t a);
  typedef enum logic {OFF, ON} sw_t;
  sw_t sw;
  enum {X, Y} var_without_type;
  if (A) begin : g_a
    typedef struct { p::t f; } s_t;
  end
endmodule
"""
    file = parse_text(text)
    assert [item.id for item in file.iter_items()] == [
        "p",
        "p.t",
        "top",
        "top.a",
        "top.sw_t",
        "top.sw_t.OFF",
        "top.sw_t.ON",
        "top.s_t",
        "top.s_t.f",
    ]
    assert file.modules[0].ports[0].ptype == "p::t"


def test_same_name():
    """Modules And Packages Share The Names Of The File."""
    file = parse_text("module x; endmodule\npackage x; endpackage\n")
    assert [item.id for item in file.iter_items()] == ["x~2", "x"]


def test_broken():
    """Missing `endpackage`, Unclosed Members."""
    text = "package p;\n  typedef enum {A, B e_t;\n  typedef int i_t;\nmodule top; endmodule\n"
    file = parse_text(text)
    assert [(diag.code, diag.loc.line, diag.item) for diag in file.diagnostics] == [
        ("missing-end", 1, "p"),
        ("unbalanced-bracket", 2, "p"),
    ]
    assert [module.name for module in file.modules] == ["top"]
    assert [package.name for package in file.packages] == ["p"]


def test_macro_expansion():
    """Types Created By A Macro Point To The Macro Call."""
    text = "`define T(name) typedef logic [7:0] name;\npackage p;\n  `T(byte_t)\nendpackage\n"
    (typedef,) = parse_text(text, expand_macros=True).packages[0].typedefs
    assert typedef.name == "byte_t"
    assert typedef.loc == Location(line=3, col=3, end_line=3, end_col=13, macro="T")


def test_corpus_package():
    """A Real Package."""
    path = PRJ_PATH / "tests" / "corpus" / "sv" / "ibex" / "ibex_pkg.sv"
    file = parse_file(path)
    (package,) = file.packages
    assert package.name == "ibex_pkg"
    assert file.diagnostics == ()
    text = path.read_text()
    assert len(package.typedefs) == text.count("typedef ")
    opcode = file.find("ibex_pkg.opcode_e")
    assert opcode.kind == "enum"
    assert opcode.members[0] == file.find("ibex_pkg.opcode_e.OPCODE_LOAD")
    assert opcode.members[0].value == "7'h03"
    for typedef in package.typedefs:
        assert typedef.kind == "alias" or typedef.members, typedef.name
        for item in (typedef, *typedef.members):
            assert item.name in _text_at(text, item.loc)


def test_tolerant():
    """Lifetime, Packages Without Name, Stray Brackets And Unclosed Structs."""
    text = "package;\npackage automatic p;\n  )\n  typedef int i_t;\n  typedef struct { int a;\nendpackage\n"
    file = parse_text(text)
    (package,) = file.packages
    assert [typedef.name for typedef in package.typedefs] == ["i_t"]
    assert [diag.code for diag in file.diagnostics] == ["unbalanced-bracket"]
