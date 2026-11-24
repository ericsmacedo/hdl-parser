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

"""Source Locations."""

from pathlib import Path

from pytest import mark

from hdl_parser import Location, parse_defines_text, parse_file, parse_text
from hdl_parser._sv.preproc import read_text

from .conftest import EXAMPLES_PATH, PRJ_PATH

CORPUS = tuple(
    sorted(
        path for path in (PRJ_PATH / "tests" / "corpus").rglob("*.*") if path.suffix in (".sv", ".v", ".vhd", ".vhdl")
    )
)
MACRO_EXAMPLES = tuple(sorted((EXAMPLES_PATH / "sv" / "macros").glob("*.sv")))


def _text_at(text: str, loc: Location) -> str:
    """Source text at `loc`."""
    lines = text.split("\n")
    if loc.line == loc.end_line:
        return lines[loc.line - 1][loc.col - 1 : loc.end_col - 1]
    return "\n".join(
        (
            lines[loc.line - 1][loc.col - 1 :],
            *lines[loc.line : loc.end_line - 1],
            lines[loc.end_line - 1][: loc.end_col - 1],
        )
    )


def _items(file):
    for mod in file.modules:
        yield mod
        yield from mod.params
        yield from mod.localparams
        yield from mod.ports
        yield from mod.unresolved_macros
        for inst in mod.insts:
            yield inst
            yield from inst.connections


def test_sv():
    """Every Item Points Into The Source."""
    text = """\
// header
module top #(
  parameter int W = 8, D = 2
) (
  input  logic [W-1:0] a, b,
  output logic         c
);
  localparam X = W + 1;
  sub #(.W(W)) u0 (.x(a), .y, b), u1 ();
endmodule
"""
    mod = parse_text(text).modules[0]
    assert _text_at(text, mod.loc).startswith("module top")
    assert _text_at(text, mod.loc).endswith("endmodule")
    assert mod.loc == Location(line=2, col=1, end_line=10, end_col=10)
    w, d = mod.params
    assert _text_at(text, w.loc) == "parameter int W = 8, D = 2"
    assert d.loc == w.loc
    a, b, c = mod.ports
    assert _text_at(text, a.loc) == "input  logic [W-1:0] a, b"
    assert b.loc == a.loc
    assert _text_at(text, c.loc) == "output logic         c"
    assert _text_at(text, mod.localparams[0].loc) == "localparam X = W + 1;"
    u0, u1 = mod.insts
    assert _text_at(text, u0.loc) == "sub #(.W(W)) u0 (.x(a), .y, b), u1 ();"
    assert u1.loc == u0.loc
    assert [_text_at(text, con.loc) for con in u0.connections] == [".x(a)", ".y", "b"]
    assert all(not item.loc.macro for item in _items(parse_text(text)))


def test_vhdl():
    """Entity, Generics, Ports, Instances And Connections."""
    text = """\
library ieee;
use ieee.std_logic_1164.all;

entity top is
  generic (W : natural := 8);
  port (
    a, b : in  std_logic;
    c    : out std_logic_vector(W-1 downto 0)
  );
end entity top;

architecture rtl of top is
begin
  u0 : entity work.sub port map (x => a, y => c);
end architecture;
"""
    mod = parse_text(text, lang="vhdl").modules[0]
    assert _text_at(text, mod.loc).startswith("entity top is")
    assert _text_at(text, mod.loc).endswith("end entity top;")
    assert _text_at(text, mod.params[0].loc) == "W : natural := 8"
    a, b, c = mod.ports
    assert _text_at(text, a.loc) == "a, b : in  std_logic"
    assert b.loc == a.loc
    assert _text_at(text, c.loc) == "c    : out std_logic_vector(W-1 downto 0)"
    inst = mod.insts[0]
    assert _text_at(text, inst.loc) == "u0 : entity work.sub port map (x => a, y => c);"
    assert [_text_at(text, con.loc) for con in inst.connections] == ["x => a", "y => c"]


def test_vhdl_architecture_only():
    """Without Entity, The Module Points To The Architecture."""
    text = "architecture rtl of top is\nbegin\nend rtl;\n"
    mod = parse_text(text, lang="vhdl").modules[0]
    assert _text_at(text, mod.loc) == text.rstrip("\n")


def test_macro():
    """Code Created By A Macro Points To The Outermost Call."""
    text = """\
`define PORT(name) input logic name,
`define PAIR(a, b) `PORT(a) `PORT(b)
`define SUFFIX _o
module top (
  `PORT(x)
    `PAIR(y, z)
  output logic q`SUFFIX
);
  `UNKNOWN(1)
endmodule
"""
    mod = parse_text(text, expand_macros=True).modules[0]
    x, y, z, q = mod.ports
    assert _text_at(text, x.loc) == "`PORT(x)"
    assert x.loc.macro == "PORT"
    assert _text_at(text, y.loc) == "`PAIR(y, z)"
    assert y.loc.macro == z.loc.macro == "PAIR"
    # partly written in the source: the name decides
    assert _text_at(text, q.loc) == "output logic q`SUFFIX"
    assert q.loc.macro == "SUFFIX"
    # everything behind the macros is not shifted
    assert _text_at(text, mod.loc).startswith("module top")
    assert _text_at(text, mod.loc).endswith("endmodule")
    assert not mod.loc.macro


def test_macro_off():
    """Without Expansion, Macros In The Header Are Reported With Their Location."""
    text = "module top (\n  `PORTS(a,\n         b)\n);\nendmodule\n"
    mod = parse_text(text).modules[0]
    assert _text_at(text, mod.unresolved_macros[0].loc) == "`PORTS(a,\n         b)"
    assert not mod.unresolved_macros[0].loc.macro


def test_macro_instance():
    """Instance Created By A Macro."""
    text = "`define INST(n) sub n (.a(a));\nmodule top;\n  `INST(u0)\n  sub u1 (.a(a));\nendmodule\n"
    u0, u1 = parse_text(text, expand_macros=True).modules[0].insts
    assert _text_at(text, u0.loc) == "`INST(u0)"
    assert u0.loc.macro == "INST"
    assert u0.connections[0].loc == u0.loc
    assert _text_at(text, u1.loc) == "sub u1 (.a(a));"
    assert not u1.loc.macro


def test_resolved_ifdefs():
    """Removed Code Does Not Shift The Locations."""
    text = """\
module top (
`ifdef FEATURE
  input  logic a,
`else
  input  logic b,
`endif
  output logic c
);
endmodule
"""
    macros = parse_defines_text("`define FEATURE").macros
    mod = parse_text(text, expand_macros=True, macros=macros, resolve_ifdefs=True).modules[0]
    a, c = mod.ports
    assert a.loc == Location(line=3, col=3, end_line=3, end_col=17)
    assert c.loc == Location(line=7, col=3, end_line=7, end_col=17)
    assert _text_at(text, mod.loc).endswith("endmodule")


def test_columns_are_characters(tmp_path):
    """Columns Count Characters, Tabs Count One. Latin-1 And CRLF Files."""
    text = "// \xe4\xf6\xfc\nmodule top (\n\t/* \xe9 */ input a\n);\nendmodule\n"
    port = parse_text(text).modules[0].ports[0]
    assert port.loc == Location(line=3, col=10, end_line=3, end_col=17)
    path = tmp_path / "top.sv"
    path.write_bytes(text.replace("\n", "\r\n").encode("latin-1"))
    assert parse_file(path).modules[0].ports[0].loc == port.loc


def test_overview():
    """Locations Are Part Of The JSON Output."""
    assert '"loc"' in parse_text("module top (input a); endmodule").overview


def _check(path: Path, file) -> None:
    text = read_text(path)
    lines = text.split("\n")
    for item in _items(file):
        loc = item.loc
        assert loc is not None, item
        assert 1 <= loc.line <= loc.end_line <= len(lines), item
        assert (loc.line, loc.col) < (loc.end_line, loc.end_col), item
        if loc.macro:
            continue
        found = _text_at(text, loc)
        name = getattr(item, "name", "") or getattr(item, "port", "")
        if name:
            assert name.lower() in found.lower(), (item, found)


@mark.parametrize("path", CORPUS, ids=lambda path: str(path.relative_to(PRJ_PATH / "tests" / "corpus")))
def test_corpus(path):
    """Every Item Of The Corpus Points To A Source Range Containing Its Name."""
    _check(path, parse_file(path))


@mark.parametrize("path", MACRO_EXAMPLES, ids=lambda path: path.name)
def test_macro_examples(path):
    """Every Item Of The Macro Examples Points To A Source Range Containing Its Name, Or A Macro Call."""
    for file in (parse_file(path, expand_macros=True), parse_file(path, expand_macros=True, resolve_ifdefs=True)):
        _check(path, file)
        text = read_text(path)
        for item in _items(file):
            if item.loc.macro:
                assert "`" in _text_at(text, item.loc), item
