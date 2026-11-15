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

"""Identifiers."""

from pathlib import Path

from pytest import mark

from hdl_parser import parse_file, parse_text

from .conftest import EXAMPLES_PATH, PRJ_PATH

CORPUS = tuple(
    sorted(
        path for path in (PRJ_PATH / "tests" / "corpus").rglob("*.*") if path.suffix in (".sv", ".v", ".vhd", ".vhdl")
    )
)
MACRO_EXAMPLES = tuple(sorted((EXAMPLES_PATH / "sv" / "macros").glob("*.sv")))

TEXT = """\
module top #(parameter int W = 8) (
  input  logic [W-1:0] a,
  output logic         q
);
  localparam X = 1;
  sub u_named (.a(a), .q);
  sub u_order (a, q);
endmodule
"""


def _ids(file) -> list[str]:
    return [item.id for item in file.iter_items()]


def test_sv():
    """Hierarchical Names Of All Items."""
    assert _ids(parse_text(TEXT)) == [
        "top",
        "top.W",
        "top.X",
        "top.a",
        "top.q",
        "top.u_named",
        "top.u_named.a",
        "top.u_named.q",
        "top.u_order",
        "top.u_order.#1",
        "top.u_order.#2",
    ]


def test_vhdl():
    """VHDL Names Are Lower Case."""
    text = """\
entity Top is
  generic (Width : natural := 8);
  port (CLK : in std_logic);
end;
architecture rtl of top is
begin
  U0 : entity work.Sub port map (Clk => CLK);
  U1 : entity work.Sub port map (CLK);
end;
"""
    assert _ids(parse_text(text, lang="vhdl")) == [
        "top",
        "top.width",
        "top.clk",
        "top.u0",
        "top.u0.clk",
        "top.u1",
        "top.u1.#1",
    ]


def test_duplicates():
    """A Name Used Again Gets A Suffix."""
    text = """\
module top (
`ifdef A
  input logic a,
`else
  input logic [1:0] a,
`endif
  `PORTS
  `PORTS
);
  sub u0 (.a(a));
  sub u0 (.a(a));
endmodule
module top; endmodule
"""
    file = parse_text(text)
    assert _ids(file) == [
        "top",
        "top.a",
        "top.a~2",
        "top.`PORTS",
        "top.`PORTS~2",
        "top.u0",
        "top.u0.a",
        "top.u0~2",
        "top.u0~2.a",
        "top~2",
    ]
    assert file.find("top.a~2").dim == "[1:0]"


def test_escape():
    """Separators Within Escaped Identifiers Are Percent-Encoded."""
    file = parse_text("module top (input \\a.b:c#d~e%f );\nendmodule\n")
    assert file.modules[0].ports[0].id == "top.\\a%2Eb%3Ac%23d%7Ee%25f"
    assert file.find(file.modules[0].ports[0].id) is file.modules[0].ports[0]


def test_stable():
    """Unrelated Edits Do Not Change Identifiers."""
    edited = "// a new header comment\n\n" + TEXT.replace(
        "  input  logic [W-1:0] a,\n", "  input  logic [W-1:0] a, // comment\n  input  logic b,\n"
    ).replace("  localparam X = 1;\n", "  localparam X = 2;\n  logic unused;\n  sub u_new ();\n")
    before = set(_ids(parse_text(TEXT)))
    after = set(_ids(parse_text(edited)))
    assert before <= after
    assert after - before == {"top.b", "top.unused", "top.u_new"}


def test_find_and_full_id(tmp_path, monkeypatch):
    """Lookup By Local And Full Identifier."""
    file = parse_text(TEXT, file_path="rtl/top.sv")
    port = file.modules[0].ports[1]
    assert file.full_id(port) == "rtl/top.sv:top.q"
    assert file.find("top.q") is port
    assert file.find("rtl/top.sv:top.q") is port
    assert file.find("other.sv:top.q") is None
    assert file.find("top.missing") is None
    assert parse_text(TEXT).full_id("top") == "<text>:top"
    # absolute paths below the current directory are relative
    monkeypatch.chdir(tmp_path)
    assert parse_text(TEXT, file_path=tmp_path / "rtl" / "top.sv").file_id == "rtl/top.sv"
    outside = Path("/elsewhere/top.sv")
    assert parse_text(TEXT, file_path=outside).file_id == "/elsewhere/top.sv"


def _check_unique(file) -> None:
    ids = _ids(file)
    assert all(ids), file.path
    assert len(ids) == len(set(ids)), [item for item in ids if ids.count(item) > 1]
    for item in file.iter_items():
        assert file.find(item.id) is item


@mark.parametrize("path", CORPUS, ids=lambda path: str(path.relative_to(PRJ_PATH / "tests" / "corpus")))
def test_corpus(path):
    """Identifiers Are Unique And Found Again."""
    _check_unique(parse_file(path))


@mark.parametrize("path", MACRO_EXAMPLES, ids=lambda path: path.name)
def test_macro_examples(path):
    """Identifiers Are Unique With And Without Macro Expansion."""
    _check_unique(parse_file(path))
    _check_unique(parse_file(path, expand_macros=True, resolve_ifdefs=True))
