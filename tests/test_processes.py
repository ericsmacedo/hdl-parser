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

"""Always Blocks With Their Clock And Reset."""

import re

from pytest import mark

from hdl_parser import Event, Generate, Process, parse_file, parse_text

from .conftest import PRJ_PATH, plain

CORPUS = tuple(sorted((PRJ_PATH / "tests" / "corpus" / "sv").glob("*/*.sv")))

TEXT = """\
module top (input logic clk_i, rst_ni);
  // Data register
  always_ff @(posedge clk_i or negedge rst_ni) begin : p_reg
    if (!rst_ni) begin
      q <= '0;
    end else begin
      q <= d;
    end
  end

  always_ff @(posedge clk_i) q2 <= d2;
  always @(negedge clk_n, posedge arst)
    if (arst) q3 <= 0;
    else q3 <= d3;
  always_comb begin
    d = q + 1;
  end
  always @* d2 = q2;
  always @(a or b[0] or c.d) e = a;
  always_latch if (en) l = d;
  always @(posedge clk_i iff en) q4 <= d4;
  always @(posedge clk_i or negedge rst_ni) q5 <= d5;
  always @(posedge clk_a or posedge clk_b or negedge rst_ni) if (!rst_ni) q6 <= 0;
  always_ff @(posedge clk_i) if (!rst_ni) q7 <= 0; else q7 <= d7;
  always_ff @(posedge (clk_i) or negedge (rst_ni)) if (!rst_ni) q8 <= 0;
  always #5 clk = ~clk;
  always @clk x = y;
  initial begin z = 0; end
  for (genvar i = 0; i < 2; i++) begin : g_stage
    always_ff @(posedge clk_i) begin : p_stage
      s[i] <= d;
    end
    always_comb t[i] = s[i];
  end
endmodule
"""


def _overview(module) -> list[tuple]:
    return [
        (
            proc.id,
            proc.kind,
            " ".join(f"{event.edge} {event.signal}".strip() for event in proc.events),
            f"{proc.clock_edge} {proc.clock}".strip(),
            f"{proc.reset_edge} {proc.reset}".strip(),
        )
        for proc in module.processes
    ]


def test_processes():
    """Sensitivity List, Clock And Reset."""
    (module,) = parse_text(TEXT).modules
    assert _overview(module) == [
        ("top.p_reg", "always_ff", "posedge clk_i negedge rst_ni", "posedge clk_i", "negedge rst_ni"),
        ("top.#always2", "always_ff", "posedge clk_i", "posedge clk_i", ""),
        ("top.#always3", "always", "negedge clk_n posedge arst", "negedge clk_n", "posedge arst"),
        ("top.#always4", "always_comb", "", "", ""),
        ("top.#always5", "always", "", "", ""),
        ("top.#always6", "always", "a b[0] c.d", "", ""),
        ("top.#always7", "always_latch", "", "", ""),
        ("top.#always8", "always", "posedge clk_i", "posedge clk_i", ""),
        # two edges, but none is checked first: clock and reset are not known
        ("top.#always9", "always", "posedge clk_i negedge rst_ni", "", ""),
        # two edges are left: the clock is not known
        ("top.#always10", "always", "posedge clk_a posedge clk_b negedge rst_ni", "", ""),
        # a reset which is not part of the sensitivity list is a condition like any other
        ("top.#always11", "always_ff", "posedge clk_i", "posedge clk_i", ""),
        ("top.#always12", "always_ff", "posedge clk_i negedge rst_ni", "posedge clk_i", "negedge rst_ni"),
        ("top.#always13", "always", "", "", ""),
        ("top.#always14", "always", "clk", "", ""),
        ("top.g_stage.p_stage", "always_ff", "posedge clk_i", "posedge clk_i", ""),
        ("top.g_stage.#always16", "always_comb", "", "", ""),
    ]


def test_model():
    """Comment, Generate Constructs, Location And Output."""
    file = parse_text(TEXT)
    assert file.diagnostics == ()
    proc = file.find("top.p_reg")
    assert [(assign.target, assign.reads, assign.conds, assign.blocking) for assign in proc.assigns] == [
        ("q", (), ("rst_ni",), False),
        ("q", ("d",), ("rst_ni",), False),
    ]
    assert plain(proc).model_copy(update={"assigns": ()}) == Process(
        name="p_reg",
        kind="always_ff",
        events=(Event(edge="posedge", signal="clk_i"), Event(edge="negedge", signal="rst_ni")),
        clock="clk_i",
        clock_edge="posedge",
        reset="rst_ni",
        reset_edge="negedge",
        comment=("Data register",),
    )
    assert (proc.loc.line, proc.loc.col, proc.loc.end_line) == (3, 3, 9)
    stage = file.find("top.g_stage.p_stage")
    assert stage.generates == (Generate(kind="for", name="g_stage", cond="genvar i = 0; i < 2; i++"),)
    assert '"processes"' in file.overview


def test_following_items():
    """The Items Behind A Block Are Not Part Of It."""
    text = """\
module top;
  always_ff @(posedge clk) if (a) b <= c; else if (d) b <= e;
  sub u0 ();
  always_comb
    case (x)
      1: y = 0;
      default: y = 1;
    endcase
  logic sig;
endmodule
"""
    (module,) = parse_text(text).modules
    assert [proc.loc.end_line for proc in module.processes] == [2, 8]
    assert [inst.name for inst in module.insts] == ["u0"]
    assert [signal.name for signal in module.signals] == ["sig"]


def test_macro():
    """A Block Created By A Macro Points To The Macro Call."""
    text = """\
`define FF(q, d) always_ff @(posedge clk_i or negedge rst_ni) if (!rst_ni) q <= '0; else q <= d;
module top;
  `FF(a_q, a_d)
endmodule
"""
    assert parse_text(text).modules[0].processes == ()
    (proc,) = parse_text(text, expand_macros=True).modules[0].processes
    assert (proc.clock, proc.reset, proc.loc.line, proc.loc.macro) == ("clk_i", "rst_ni", 3, "FF")


@mark.parametrize("path", CORPUS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_corpus(path):
    """All Always Blocks Of Real Code Are Found. Clock And Reset Are Part Of The Sensitivity List."""
    text = path.read_text()
    lines = text.split("\n")
    file = parse_file(path)
    processes = [proc for module in (*file.interfaces, *file.modules) for proc in module.processes]
    # macro definitions are no blocks
    code = re.sub(r"^`define.*?[^\\]$", "", text, flags=re.MULTILINE | re.DOTALL)
    assert [proc.kind for proc in processes] == re.findall(r"^\s*(always\w*)\b", code, re.MULTILINE)
    for proc in processes:
        assert lines[proc.loc.line - 1].lstrip().startswith(proc.kind)
        header = " ".join(lines[proc.loc.line - 1 : proc.loc.line + 2])
        edges = {event.signal: event.edge for event in proc.events if event.edge}
        for event in proc.events:
            assert event.signal in header
        if proc.clock:
            assert edges[proc.clock] == proc.clock_edge
        if proc.reset:
            assert edges[proc.reset] == proc.reset_edge
            assert proc.clock
            assert proc.reset != proc.clock
        if proc.kind in ("always_comb", "always_latch"):
            assert not proc.events
        if proc.kind == "always_ff":
            assert edges
        if proc.name:
            assert re.search(rf"begin\s*:\s*{proc.name}\b", text)


def test_corpus_has_processes():
    """The Corpus Covers Clocked Blocks With And Without Reset, And Combinational Blocks."""
    files = [parse_file(path) for path in CORPUS]
    processes = [proc for file in files for module in (*file.interfaces, *file.modules) for proc in module.processes]
    assert len(processes) >= 170
    assert sum(proc.kind == "always_ff" for proc in processes) >= 90
    assert sum(proc.kind == "always_comb" for proc in processes) >= 70
    assert sum(bool(proc.clock) for proc in processes) >= 95
    assert sum(bool(proc.reset) for proc in processes) >= 85
    assert sum(bool(proc.clock and not proc.reset) for proc in processes) >= 10
    assert sum(bool(proc.name) for proc in processes) >= 20
    assert sum(bool(proc.generates) for proc in processes) >= 20
    # all but one clocked block of the corpus have a known clock
    unknown = [proc for proc in processes if proc.kind == "always_ff" and not proc.clock]
    assert len(unknown) == 1


def test_corpus_macro_blocks():
    """Real Code Creating Registers By Macros: The Blocks Are Known With Macro Expansion Only."""
    corpus = PRJ_PATH / "tests" / "corpus" / "sv"
    path = corpus / "common_cells" / "cdc_fifo_gray.sv"
    assert "`FFLARN(wptr_q, wptr_d" in path.read_text()
    plain_procs = [proc for module in parse_file(path).modules for proc in module.processes]
    expanded = parse_file(path, expand_macros=True, inc_dirs=[corpus])
    procs = [proc for module in expanded.modules for proc in module.processes]
    by_macro = [proc for proc in procs if proc.loc.macro]
    assert len(procs) == len(plain_procs) + len(by_macro)
    assert {proc.loc.macro for proc in by_macro} == {"FFLNR", "FFLARN"}
    wptr = next(proc for proc in by_macro if proc.loc.line == 216)
    assert (wptr.clock, wptr.clock_edge, wptr.reset, wptr.reset_edge) == (
        "src_clk_i",
        "posedge",
        "src_rst_ni",
        "negedge",
    )
