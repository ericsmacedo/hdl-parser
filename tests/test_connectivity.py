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

"""Connectivity: Assignments, Drivers, Loads And Traces."""

import json
from pathlib import Path

from pytest import fixture, mark, raises
from test2ref import assert_refdata

from hdl_parser import Project, parse_text, query
from hdl_parser._mcp import Server
from hdl_parser.cli import cli

from .conftest import PRJ_PATH, objects

CORPUS = PRJ_PATH / "tests" / "corpus"


def _assigns(assigns) -> list[tuple]:
    return [(assign.target, assign.select, assign.reads, assign.conds, assign.blocking) for assign in assigns]


# --- assignments: SystemVerilog ---


def test_sv_continuous():
    """`assign`, Concatenation, Net Declaration, Parameters Left Out."""
    text = """\
module top #(parameter int W = 8) (input logic [W-1:0] a, b, output logic [W-1:0] y);
  localparam int L = 2;
  typedef enum logic {IDLE, BUSY} st_e;
  wire c = a[0] ^ b[0];
  logic v = a[1];
  assign y = a & b | W, {u, v2[L]} = {a, b};
  assign #1 z = pkg::C + f(a) + s.f + IDLE + logic'(b);
  function automatic logic f(logic x); return x; endfunction
endmodule
"""
    (module,) = parse_text(text).modules
    assert _assigns(module.assigns) == [
        ("c", "", ("a", "b"), (), True),
        ("y", "", ("a", "b"), (), True),
        ("u", "", ("a", "b"), (), True),
        ("v2", "[L]", ("a", "b"), (), True),
        ("z", "", ("a", "s", "b"), (), True),
    ]
    assert module.assigns[0].loc.line == 4
    assert module.assigns[1].loc.line == 6


def test_sv_process():
    """Conditions, Case, Loops, Compound Assignments, Variables, Selects."""
    text = """\
module top (input logic clk, rst_n, en, input logic [1:0] sel, input logic [7:0] a, b, d, idx);
  always_ff @(posedge clk or negedge rst_n) begin : p_reg
    if (!rst_n) q <= '0;
    else if (en) begin
      q <= a;
      m[idx] <= #1 d;
    end
  end
  always_comb begin
    automatic logic [3:0] t = a[3:0];
    y = '0;
    unique case (sel)
      2'd0: y = t;
      2'd1, 2'd2: begin y = b; y += 1; end
      default: ;
    endcase
    for (int i = 0; i < 8; i++) z[i] = a[i];
    w++;
    $display("%d", a);
    if (en) my_task(a, y);
  end
endmodule
"""
    file = parse_text(text)
    (module,) = file.modules
    ff, comb = module.processes
    assert _assigns(ff.assigns) == [
        ("q", "", (), ("rst_n",), False),
        ("q", "", ("a",), ("rst_n", "en"), False),
        ("m", "[idx]", ("d", "idx"), ("rst_n", "en"), False),
    ]
    assert _assigns(comb.assigns) == [
        ("t", "", ("a",), (), True),
        ("y", "", (), (), True),
        ("y", "", ("t",), ("sel",), True),
        ("y", "", ("b",), ("sel",), True),
        ("y", "", ("y",), ("sel",), True),
        ("z", "[i]", ("a", "i"), ("i",), True),
        ("w", "", ("w",), (), True),
    ]
    # task calls are not understood: they are reported
    (diag,) = file.diagnostics
    assert diag.code == "statement-skipped"
    assert diag.severity == "info"
    assert "my_task(a, y)" in diag.message
    assert (diag.loc.line, diag.item) == (20, "top")


def test_sv_wildcard():
    """Connections By `.*` Are Marked."""
    (module,) = parse_text("module top; sub u (.*, .a(b)); sub v (.a(b)); endmodule").modules
    assert [inst.wildcard for inst in module.insts] == [True, False]
    assert [con.port for con in module.insts[0].connections] == ["a"]


def test_sv_generate_alternatives():
    """The Alternatives Of A Generate `if` Know The Conditions In Front."""
    text = """\
module top;
  if (A) begin : g_a
    assign x = 1;
  end else if (B) begin : g_b
    assign x = 2;
  end else begin : g_c
    assign x = 3;
  end
  if (C) assign y = 1;
  else assign y = 2;
endmodule
"""
    (module,) = parse_text(text).modules
    generates = [(gen.kind, gen.cond, gen.others) for assign in module.assigns for gen in assign.generates]
    assert generates == [
        ("if", "A", ()),
        ("if", "B", ("A",)),
        ("else", "", ("A", "B")),
        ("if", "C", ()),
        ("else", "", ("C",)),
    ]


# --- assignments: VHDL ---

VHDL = """\
library ieee; use ieee.std_logic_1164.all;
entity top is
  generic (W : natural := 8; USE_B : boolean := false);
  port (clk, rst_n, sel : in std_logic; a, b : in std_logic_vector(W-1 downto 0);
        y, q, z : out std_logic_vector(W-1 downto 0));
end entity;
architecture rtl of top is
  type st_t is (IDLE, BUSY);
  signal st : st_t;
  signal t, u : std_logic_vector(W-1 downto 0);
  constant C : natural := 3;
begin
  t <= a and b;
  lbl : u <= a when sel = '1' else b;
  with st select y <= a when IDLE, b when others;
  p_reg : process (clk, rst_n)
    variable v : std_logic_vector(W-1 downto 0);
  begin
    if rst_n = '0' then
      q <= (others => '0');
    elsif rising_edge(clk) then
      v := t xor u;
      case st is
        when IDLE => q(C downto 0) <= v(C downto 0);
        when others => null;
      end case;
      for i in 0 to W-1 loop
        q(i) <= v(i);
      end loop;
      my_proc(a, q);
    end if;
  end process;
  g_b : if USE_B generate
    z <= a;
  else generate
    z <= b;
  end generate;
end architecture;
"""


def test_vhdl_assignments():
    """Concurrent, Conditional And Selected Assignments, Processes, Variables."""
    file = parse_text(VHDL, lang="vhdl")
    (module,) = file.modules
    assert _assigns(module.assigns) == [
        ("t", "", ("a", "b"), (), True),
        ("u", "", ("a", "b"), ("sel",), True),
        ("y", "", ("a", "b"), ("st",), True),
        ("z", "", ("a",), (), True),
        ("z", "", ("b",), (), True),
    ]
    assert [assign.generates[0].kind for assign in module.assigns[3:]] == ["if", "else"]
    assert module.assigns[4].generates[0].others == ("USE_B",)
    (process,) = module.processes
    assert _assigns(process.assigns) == [
        ("q", "", (), ("rst_n",), False),
        ("v", "", ("t", "u"), ("rst_n", "rising_edge", "clk"), True),
        ("q", "(C downto 0)", ("v",), ("rst_n", "rising_edge", "clk", "st"), False),
        ("q", "(i)", ("v", "i"), ("rst_n", "rising_edge", "clk", "i"), False),
    ]
    (diag,) = file.diagnostics
    assert diag.code == "statement-skipped"
    assert "my_proc(a, q)" in diag.message


# --- project ---


@fixture
def design(tmp_path) -> Project:
    """Small Mixed Design."""
    (tmp_path / "top.sv").write_text("""\
module top #(parameter bit USE_B = 0) (input logic clk_i, rst_ni, input logic [7:0] a_i, output logic [7:0] y_o);
  logic [7:0] s, r, p, w;
  sub u_sub (.clk_i, .d_i(a_i), .q_o(s));
  sub u_pos (clk_i, r, p);
  vsub u_v (.clk(clk_i), .d(p), .q(w));
  assign r = s + 1;
  if (USE_B) begin : g_b
    assign y_o = 0;
  end else begin : g_n
    always_comb y_o = w;
  end
  bb u_bb (.x(r), .y(unused));
endmodule
""")
    (tmp_path / "sub.sv").write_text("""\
module sub (input logic clk_i, input logic [7:0] d_i, output logic [7:0] q_o);
  logic [7:0] q;
  always_ff @(posedge clk_i) q <= d_i;
  assign q_o = q;
endmodule
""")
    (tmp_path / "vsub.vhd").write_text("""\
library ieee; use ieee.std_logic_1164.all;
entity vsub is port (clk : in std_logic; d : in std_logic_vector(7 downto 0); q : out std_logic_vector(7 downto 0));
end entity;
architecture rtl of vsub is
  signal reg : std_logic_vector(7 downto 0);
begin
  process (clk) begin
    if rising_edge(clk) then reg <= d; end if;
  end process;
  Q <= REG;
end architecture;
""")
    return Project.from_dir(tmp_path)


def _links(links) -> list[tuple]:
    return [(link.kind, link.nets, link.item) for link in links]


def test_drivers(design):
    """Assignments, Instances, Ports, Generate Constructs."""
    assert _links(design.drivers("top.y_o")) == [("comb", ("top.w",), "top.sv:top.g_n.#always1")]
    assert _links(design.drivers("top.y_o", params={"USE_B": 1})) == [("assign", (), "top.sv:top")]
    assert _links(design.drivers("top.s")) == [("inst", ("top.u_sub.q_o",), "top.sv:top.u_sub")]
    # connection by order and by name, VHDL port names are not case sensitive
    assert _links(design.drivers("top.p")) == [("inst", ("top.u_pos.q_o",), "top.sv:top.u_pos")]
    assert _links(design.drivers("top.u_v.q")) == [("assign", ("top.u_v.reg",), "vsub.vhd:vsub")]
    (ff,) = design.drivers("top.u_sub.q")
    assert (ff.kind, ff.nets, ff.clock, ff.conds) == ("ff", ("top.u_sub.d_i",), "top.u_sub.clk_i", ())
    assert ff.loc.line == 3
    # input ports: driven by the parent, or from outside
    assert _links(design.drivers("top.u_sub.d_i")) == [("port", ("top.a_i",), "top.sv:top.u_sub")]
    assert _links(design.drivers("top.u_pos.d_i")) == [("port", ("top.r",), "top.sv:top.u_pos")]
    (external,) = design.drivers("top.a_i")
    assert (external.kind, external.external) == ("port", True)
    # blackbox: the direction is not known
    (unknown,) = design.drivers("top.unused")
    assert unknown.kind == "unknown"
    assert unknown.unknown == "module 'bb' is not defined in the project"


def test_loads(design):
    """Assignments, Clocks, Instances, Output Ports."""
    assert _links(design.loads("top.r")) == [
        ("inst", ("top.u_pos.d_i",), "top.sv:top.u_pos"),
        ("unknown", (), "top.sv:top.u_bb"),
    ]
    (clock,) = design.loads("top.u_sub.clk_i")
    assert (clock.kind, clock.nets, clock.control) == ("ff", ("top.u_sub.q",), True)
    assert _links(design.loads("top.u_sub.q_o")) == [("port", ("top.s",), "top.sv:top.u_sub")]
    (external,) = design.loads("top.y_o")
    assert external.external


def test_trace(design):
    """Through The Hierarchy, Stopped By Flip-Flops."""
    assert design.trace("top.a_i", "top.y_o") == ()
    hops = design.trace("top.a_i", "top.y_o", through_regs=True)
    assert [(hop.net, hop.kind) for hop in hops] == [
        ("top.a_i", ""),
        ("top.u_sub.d_i", "inst"),
        ("top.u_sub.q", "ff"),
        ("top.u_sub.q_o", "assign"),
        ("top.s", "port"),
        ("top.r", "assign"),
        ("top.u_pos.d_i", "inst"),
        ("top.u_pos.q", "ff"),
        ("top.u_pos.q_o", "assign"),
        ("top.p", "port"),
        ("top.u_v.d", "inst"),
        ("top.u_v.reg", "ff"),
        ("top.u_v.q", "assign"),
        ("top.w", "port"),
        ("top.y_o", "comb"),
    ]
    # control: the clock reaches the flip-flops
    assert [hop.net for hop in design.trace("top.clk_i", "top.u_sub.q")] == [
        "top.clk_i",
        "top.u_sub.clk_i",
        "top.u_sub.q",
    ]
    assert design.trace("top.clk_i", "top.u_sub.q", control=False) == ()


def test_paths(design):
    """Full Identifiers, Indices, Generate Labels, Errors With Suggestions."""
    assert design.drivers("top.sv:top.u_sub.q[0]") == design.drivers("top.u_sub.q")
    with raises(ValueError, match=r"'top\.u_sub' is no instance array"):
        design.drivers("top.u_sub[0].q")
    with raises(ValueError, match="has no instance or generate block 'u_nope'") as exc:
        design.drivers("top.u_nope.x")
    with raises(ValueError, match="has no signal 'qq'") as exc:
        design.drivers("top.u_sub.qq")
    assert exc.value.suggestions == ("q",)
    with raises(ValueError, match="is no module"):
        design.drivers("tpo.a_i")
    with raises(ValueError, match="no signal"):
        design.drivers("top")
    with raises(ValueError, match=r"'bb' of 'top\.u_bb' is not known"):
        design.drivers("top.u_bb.x")


def test_variables(tmp_path):
    """Variables Of Processes Connect Their Assignments."""
    text = """\
module top (input logic [7:0] a, output logic [7:0] y);
  always_comb begin : p_c
    automatic logic [7:0] tmp;
    tmp = a + 1;
    y = tmp;
  end
endmodule
"""
    project = _project(tmp_path, {"top.sv": text})
    assert _links(project.drivers("top.y")) == [("comb", ("top.p_c.tmp",), "top.sv:top.p_c")]
    assert [hop.net for hop in project.trace("top.a", "top.y")] == ["top.a", "top.p_c.tmp", "top.y"]


def test_wildcard_and_implicit(tmp_path):
    """Connections By `.*`, Implicit Nets, Instance Arrays."""
    files = {
        "top.sv": "module top (input a, output y); sub u_s [1:0] (.*); assign n = a; endmodule\n",
        "sub.sv": "module sub (input a, output y); assign y = a; endmodule\n",
    }
    project = _project(tmp_path, files)
    (link,) = project.drivers("top.y")
    assert (link.kind, link.nets, link.multiple) == ("inst", ("top.u_s.y",), True)
    assert _links(project.drivers("top.n")) == [("assign", ("top.a",), "top.sv:top")]


def _project(directory: Path, files: dict[str, str]) -> Project:
    for name, text in files.items():
        (directory / name).write_text(text)
    return Project.from_dir(directory)


# --- queries, command line, MCP ---


def test_query(design):
    """Answers With The Net, Limits And Errors."""
    answer = query.drivers(design, "top.u_sub.q")
    assert answer["net"] == {
        "path": "top.u_sub.q",
        "kind": "signal",
        "id": "sub.sv:sub.q",
        "file": "sub.sv",
        "loc": {"line": 2, "col": 3, "end_line": 2, "end_col": 17},
    }
    assert answer["total"] == 1
    assert answer["result"][0]["kind"] == "ff"
    answer = query.loads(design, "top.r", limit=1)
    assert (answer["total"], answer["omitted"]) == (2, 1)
    assert query.loads(design, "top.a_i")["net"]["direction"] == "input"
    answer = query.trace(design, "top.a_i", "top.y_o")
    assert answer["found"] is False
    assert "through_regs" in answer["hint"]
    assert query.trace(design, "top.a_i", "top.y_o", through_regs=True)["total"] == 15
    with raises(query.QueryError) as exc:
        query.drivers(design, "top.u_sub.qq")
    assert exc.value.code == "not-found"
    with raises(query.QueryError) as exc:
        query.trace(design, "top.a_i", "sub.q")
    assert exc.value.code == "bad-argument"


def test_cli(runner, design):
    """Commands."""
    root = str(design.root)
    result = runner.invoke(cli, ["drivers", "top.u_sub.q", root])
    assert result.exit_code == 0
    assert objects(json.loads(result.stdout)["result"])[0]["kind"] == "ff"
    result = runner.invoke(cli, ["loads", "top.u_sub.clk_i", root, "-c"])
    assert objects(json.loads(result.stdout)["result"])[0]["control"] is True
    result = runner.invoke(cli, ["trace", "top.a_i", "top.y_o", "--through-regs", root])
    assert json.loads(result.stdout)["found"] is True
    result = runner.invoke(cli, ["trace", "top.clk_i", "top.u_sub.q", "--data-only", root])
    assert json.loads(result.stdout)["found"] is False
    result = runner.invoke(cli, ["drivers", "top.y_o", "-p", "USE_B=1", root])
    assert objects(json.loads(result.stdout)["result"])[0]["kind"] == "assign"
    result = runner.invoke(cli, ["drivers", "top.nope", root])
    assert result.exit_code == 3


def test_mcp(design):
    """Tools."""
    server = Server(lambda: design, design)
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call"}
    response = server.handle({**call, "params": {"name": "drivers", "arguments": {"path": "top.s"}}})
    assert objects(response["result"]["structuredContent"]["result"])[0]["kind"] == "inst"
    arguments = {"src": "top.a_i", "dst": "top.y_o", "through_regs": True}
    response = server.handle({**call, "params": {"name": "trace", "arguments": arguments}})
    assert response["result"]["structuredContent"]["found"] is True
    arguments = {"src": "top.clk_i", "dst": "top.u_sub.q", "data_only": True}
    response = server.handle({**call, "params": {"name": "trace", "arguments": arguments}})
    assert response["result"]["structuredContent"]["found"] is False
    response = server.handle({**call, "params": {"name": "loads", "arguments": {"path": "top.x"}}})
    assert response["result"]["isError"] is True


# --- corpus ---

_TRACES = {
    "sv/ibex": (
        ("ibex_top.instr_rdata_i", "ibex_top.u_ibex_core.id_stage_i.instr_rdata_i"),
        ("ibex_top.rst_ni", "ibex_top.u_ibex_core.id_stage_i.controller_i.ctrl_fsm_cs"),
        ("ibex_top.u_ibex_core.ex_block_i.alu_i.adder_result_o", "ibex_top.u_ibex_core.id_stage_i.pc_set_o"),
    ),
    "sv/axi": (),
    "sv/common_cells": (),
    "vhdl/neorv32": (),
    "vhdl/potato": (("pp_potato.dmem_data_in", "pp_potato.processor.writeback.rd_data_in"),),
}


def _undriven(project: Project) -> list[str]:
    """Signals and outputs without driver: not used, created by a macro, or assigned through an interface."""
    from hdl_parser._conn import Connectivity  # noqa: PLC0415

    conn = Connectivity(project)
    found = []
    for definition in project._all_modules:
        graph = project._graph(definition)
        inst = conn.top(definition.id)
        assert inst is not None
        for key, net in graph.nets.items():
            node = (inst, key)
            # never a failure
            list(conn.drivers(node))
            list(conn.loads(node))
            if net.kind == "port" and net.direction != "output":
                continue
            if not graph.drivers.get(key) and not (net.item is not None and net.item.default):
                found.append(f"{definition.id}.{net.name}")
    return found


@mark.parametrize("name", sorted(_TRACES))
def test_corpus(tmp_path, name):
    """Signals Without Driver And Traces Of The Corpus."""
    project = Project.from_dir(CORPUS / name)
    lines = ["# undriven", *_undriven(project), "", "# traces"]
    for src, dst in _TRACES[name]:
        lines.append(f"{src} -> {dst}")
        hops = project.trace(src, dst, through_regs=True)
        assert hops, f"{src} -> {dst}"
        for hop in hops:
            where = f" {hop.kind} {hop.file}:{hop.loc.line}" if hop.loc else ""
            lines.append(f"  {hop.net}{where}")
    (tmp_path / "connectivity.txt").write_text("\n".join(lines) + "\n")
    assert_refdata(test_corpus, tmp_path, flavor=name.replace("/", "-"))


def test_latch_and_empty(tmp_path):
    """Latches, Empty Targets."""
    text = "module top (input en, d, output q); always_latch if (en) q = d; endmodule\n"
    project = _project(tmp_path, {"top.sv": text})
    (link,) = project.drivers("top.q")
    assert (link.kind, link.nets, link.conds) == ("latch", ("top.d",), ("top.en",))


def test_sv_conditional_operator():
    """The Select Of `?:` Is A Condition."""
    text = """\
module top (input logic s, t, input logic [7:0] a, b, output logic [7:0] y, z);
  assign y = s ? a : (t & a[0]) ? b : a;
  always_comb z = f(s ? a : b) + (s ? 1 : 0);
endmodule
"""
    (module,) = parse_text(text).modules
    assert _assigns(module.assigns) == [("y", "", ("a", "b"), ("s", "t"), True)]
    assert _assigns(module.processes[0].assigns) == [("z", "", ("a", "b"), ("s",), True)]


@fixture
def stages(tmp_path) -> Project:
    """Loops Of Stages, A Wrapper Of A Technology Cell."""
    files = {
        "top.sv": """\
module top #(parameter int N = 2) (
  input logic clk, en_i, input logic [7:0] x_i, output logic [7:0] y_o, z_o, output logic r_o, s_o
);
  logic [7:0] q;
  for (genvar i = 0; i < N; i++) begin : g_st
    logic [7:0] vl, out;
    assign vl = x_i + i;
    stage u_st (.clk, .d(vl), .q(out));
    if (i == 0) begin : g_first
      assign q = out;
    end
  end
  assign y_o = en_i ? g_st[1].vl : 8'd0;
  always_comb z_o = en_i ? q : 8'd0;
  buf_wrap u_buf (.i(x_i[0]), .o(r_o));
  BUFX2 u_cell (.A(x_i[1]), .Y(s_o));
endmodule
""",
        "stage.sv": "module stage (input logic clk, input logic [7:0] d, output logic [7:0] q);\n"
        "  assign q = d;\nendmodule\n",
        "buf_wrap.sv": """\
module buf_wrap (input logic i, output logic o);
`ifdef TECH
  BUFX2 u_b (.A(i), .Y(o));
`endif
endmodule
""",
    }
    return _project(tmp_path, files)


def test_loops(stages):
    """Iterations Are Told Apart, Indices Are Checked."""
    assert _links(stages.drivers("top.q")) == [("assign", ("top.g_st[0].out",), "top.sv:top")]
    assert _links(stages.drivers("top.g_st[1].u_st.d")) == [("port", ("top.g_st[1].vl",), "top.sv:top.g_st.u_st")]
    # a reference into a generate block from outside
    assert _links(stages.loads("top.g_st[0].vl")) == [("inst", ("top.g_st[0].u_st.d",), "top.sv:top.g_st.u_st")]
    assert [link.nets for link in stages.loads("top.g_st[1].vl")] == [("top.y_o",), ("top.g_st[1].u_st.d",)]
    # without index: all iterations
    (link,) = stages.loads("top.x_i")[:1]
    assert (link.nets, link.multiple) == (("top.g_st[0].vl", "top.g_st[1].vl"), False)
    (link,) = stages.drivers("top.g_st.vl")
    assert link.multiple
    with raises(ValueError, match=r"'top\.g_st' has no index 7: the indices are 0\.\.1\."):
        stages.drivers("top.g_st[7].vl")
    with raises(ValueError, match=r"has no index 2"):
        stages.drivers("top.g_st[2].vl", params={"N": 2})
    assert stages.drivers("top.g_st[2].vl", params={"N": 3})
    assert [hop.net for hop in stages.trace("top.x_i", "top.q")] == [
        "top.x_i",
        "top.g_st[0].vl",
        "top.g_st[0].u_st.d",
        "top.g_st[0].u_st.q",
        "top.g_st[0].out",
        "top.q",
    ]
    assert stages.trace("top.g_st[1].vl", "top.q") == ()


def test_passthrough(stages):
    """Wrappers Of Technology Cells, Cells Given As Pass-Through."""
    assert [(hop.net, hop.kind) for hop in stages.trace("top.x_i", "top.r_o")] == [
        ("top.x_i", ""),
        ("top.u_buf.i", "inst"),
        ("top.u_buf.o", "passthrough"),
        ("top.r_o", "port"),
    ]
    answer = query.trace(stages, "top.x_i", "top.s_o")
    assert answer["found"] is False
    assert "2 modules which are not defined" in answer["hint"]
    assert [(stop["item"], stop["reason"], stop["line"]) for stop in answer["stopped_at"]] == [
        ("top.sv:top.u_cell", "module 'BUFX2' is not defined in the project", 16),
        ("buf_wrap.sv:buf_wrap.u_b", "module 'BUFX2' is not defined in the project", 3),
    ]
    hops = stages.trace("top.x_i", "top.s_o", passthrough=["BUFX2:A->Y"])
    assert [(hop.net, hop.kind) for hop in hops] == [("top.x_i", ""), ("top.s_o", "passthrough")]
    (link,) = stages.drivers("top.s_o", passthrough=["BUFX2"])
    assert (link.kind, link.nets) == ("passthrough", ("top.x_i",))
    with raises(query.QueryError, match="is no pass-through cell"):
        query.trace(stages, "top.x_i", "top.s_o", passthrough=["BUFX2:A"])


def test_trace_counts(stages):
    """Hops, Flip-Flops And Conditions Of A Trace."""
    answer = query.trace(stages, "top.en_i", "top.z_o")
    assert answer["counts"] == {"hops": 1, "ff": 0, "control": 1}
    assert query.trace(stages, "top.en_i", "top.z_o", control=False)["found"] is False
