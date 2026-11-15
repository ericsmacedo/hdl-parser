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

"""Signals: Nets And Variables Of Modules And Interfaces."""

import re

from pytest import mark

from hdl_parser import Generate, Signal, parse_file, parse_text
from hdl_parser._sv.tokenizer import KEYWORDS

from .conftest import PRJ_PATH, plain

CORPUS = tuple(sorted((PRJ_PATH / "tests" / "corpus" / "sv").glob("*/*.sv")))

TEXT = """\
module top (
  input  logic       clk_i,
  output logic [7:0] data_o
);
  logic [7:0] data_d, data_q; // data register
  wire               valid = data_q[0];
  reg signed [3:0]   mem [0:15];
  my_pkg::req_t      req;
  state_t [1:0]      state_q;
  enum logic [1:0] {IDLE, BUSY} fsm_q;
  struct packed { logic a; } pair;
  const int unsigned LIMIT = 4;
  genvar i;
  typedef logic [3:0] nibble_t;
  nibble_t nibble;

  always_comb begin
    logic local_v;
    local_v = 1'b0;
  end
  function automatic logic f(logic x);
    logic tmp;
    return x;
  endfunction

  for (genvar j = 0; j < 2; j++) begin : g_stage
    logic stage_q;
    sub u_sub (.q(stage_q));
  end
  assign data_o = data_q;
  sub u_sub (.q(valid));
endmodule
"""


def _signals(module) -> list[str]:
    return [
        " ".join(
            filter(None, (sig.ptype, sig.dtype, sig.dim, sig.name, sig.dim_unpacked, sig.default and "=", sig.default))
        )
        for sig in module.signals
    ]


def test_signals():
    """Nets And Variables Of All Kinds. Nothing From Procedural Code, Functions, Ports Or Instances."""
    (module,) = parse_text(TEXT).modules
    assert _signals(module) == [
        "logic [7:0] data_d",
        "logic [7:0] data_q",
        "wire valid = data_q[0]",
        "reg signed [3:0] mem [0:15]",
        "my_pkg::req_t req",
        "state_t [1:0] state_q",
        "enum fsm_q",
        "struct pair",
        "int unsigned LIMIT = 4",
        "nibble_t nibble",
        "logic stage_q",
    ]
    assert [port.name for port in module.ports] == ["clk_i", "data_o"]
    assert [inst.id for inst in module.insts] == ["top.g_stage.u_sub", "top.u_sub"]


def test_model():
    """Comments, Generate Constructs, Identifiers And Locations."""
    file = parse_text(TEXT)
    assert file.diagnostics == ()
    data_q = file.find("top.data_q")
    assert plain(data_q) == Signal(ptype="logic", name="data_q", dim="[7:0]", comment=("data register",))
    assert (data_q.loc.line, data_q.loc.col) == (5, 3)
    assert data_q.loc == file.find("top.data_d").loc
    stage_q = file.find("top.g_stage.stage_q")
    assert stage_q.generates == (Generate(kind="for", name="g_stage", cond="genvar j = 0; j < 2; j++"),)
    assert '"signals"' in file.overview


def test_verilog_port_types():
    """The Type Of A Port, Declared On Its Own, Is No Signal."""
    text = "module top (a, q);\n  input a;\n  output q;\n  wire a;\n  reg q;\n  reg r;\nendmodule\n"
    (module,) = parse_text(text).modules
    assert [port.name for port in module.ports] == ["a", "q"]
    assert _signals(module) == ["reg r"]


def test_interface():
    """Signals Of An Interface."""
    text = (
        "interface bus_if;\n  logic [31:0] addr;\n  logic req, ack;\n"
        "  modport m (output addr, req, input ack);\nendinterface\n"
    )
    (intf,) = parse_text(text).interfaces
    assert _signals(intf) == ["logic [31:0] addr", "logic req", "logic ack"]
    assert {port.name for port in intf.modports[0].ports} == {sig.name for sig in intf.signals}


def test_no_signals():
    """Statements Are No Signals."""
    text = """\
module top;
  assign a = b;
  defparam u.P = 1;
  sub u (a);
  case (W)
    pkg::A, B: sub u0 ();
    default: ;
  endcase
  label: assert property (p);
  initial x = 1;
endmodule
"""
    assert parse_text(text).modules[0].signals == ()


@mark.parametrize("path", CORPUS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_corpus(path):
    """Signals Of Real Code Are Declared Where They Point To."""
    lines = path.read_text().split("\n")
    file = parse_file(path)
    for module in (*file.interfaces, *file.modules):
        ports = {port.name for port in module.ports}
        for signal in module.signals:
            assert re.fullmatch(r"[A-Za-z_][\w$]*", signal.name), signal
            assert signal.name not in KEYWORDS
            assert signal.name not in ports
            assert signal.ptype
            declaration = "\n".join(lines[signal.loc.line - 1 : signal.loc.end_line])
            assert re.search(rf"\b{re.escape(signal.name)}\b", declaration), signal
            assert declaration.rstrip().endswith(";") or ";" in declaration


def test_corpus_has_signals():
    """The Corpus Covers Signals Of Built-In And User-Defined Types, With And Without Generate Constructs."""
    files = [parse_file(path) for path in CORPUS]
    signals = [signal for file in files for module in (*file.interfaces, *file.modules) for signal in module.signals]
    assert len(signals) >= 1400
    assert sum(signal.ptype == "logic" for signal in signals) >= 1000
    assert sum(signal.ptype == "wire" for signal in signals) >= 10
    assert sum(signal.ptype.endswith("_t") for signal in signals) >= 200
    assert sum(bool(signal.generates) for signal in signals) >= 300
    assert sum(bool(signal.dim_unpacked) for signal in signals) >= 20
    assert sum(bool(signal.comment) for signal in signals) >= 30
    # the signals of the AXI interface
    axi = next(
        intf for intf in parse_file(PRJ_PATH / "tests/corpus/sv/axi/axi_intf.sv").interfaces if intf.name == "AXI_BUS"
    )
    assert len(axi.signals) == 45
    assert {port.name for port in axi.modports[0].ports} == {signal.name for signal in axi.signals}
