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

"""Elaboration: Values Of Parameters And Number Of Bits Of Ports, Per Instance."""

import logging
import re

from pytest import fixture, mark

from hdl_parser import HierarchyNode, Project, Value
from hdl_parser._conn import base_key

from .conftest import PRJ_PATH

CORPUS = PRJ_PATH / "tests" / "corpus"
PROJECT_DIRS = tuple(sorted(path for lang in ("sv", "vhdl") for path in (CORPUS / lang).iterdir() if path.is_dir()))

SV = {
    "pkg.sv": """\
package base_pkg;
  localparam int BASE = 4;
  typedef enum logic [1:0] {IDLE, BUSY = 2, DONE} state_e;
endpackage
package my_pkg;
  import base_pkg::*;
  localparam int AW = BASE * 4;
  localparam int unsigned DW = 32;
  typedef logic [AW-1:0] addr_t;
  typedef struct packed {
    addr_t           addr;
    logic [DW-1:0]   data;
    logic            we;
    base_pkg::state_e state;
  } req_t;
  typedef union packed { logic [7:0] b; logic [15:0] w; } u_t;
  typedef enum {A, B[2], C = B1 + 10} plain_e;
  typedef req_t req_array_t [4];
endpackage
""",
    "leaf.sv": """\
module leaf #(
  parameter int unsigned WIDTH = 8,
  parameter int unsigned DEPTH = 2 ** WIDTH,
  parameter type T = logic [3:0],
  parameter logic [7:0] MASK = '1,
  parameter NO_DEFAULT
) (
  input  logic                     clk_i,
  input  logic [WIDTH-1:0]         data_i,
  input  T                         typed_i,
  output logic [$clog2(DEPTH)-1:0] addr_o,
  output my_pkg::req_t             req_o,
  bus_if.master                    bus
);
  import my_pkg::*;
  localparam int PTR_W = $clog2(DEPTH);
  localparam int TOTAL = WIDTH + AW + my_pkg::DW;
  localparam int FN = f(WIDTH);
  localparam int LOOP_A = LOOP_B;
  localparam int LOOP_B = LOOP_A;
  localparam int STATE = base_pkg::BUSY + base_pkg::DONE;
  localparam int BITS = $bits(req_t) + $bits(data_i) + $bits(T);
  logic [PTR_W:0] ptr_q;
endmodule
""",
    "top.sv": """\
module top #(
  parameter int W = 16
) (
  input logic [W-1:0] a
);
  typedef logic [W/2-1:0] half_t;
  leaf #(.WIDTH(W), .T(half_t)) u_named ();
  leaf #(4, 8) u_ordered ();
  leaf #(.WIDTH(UNKNOWN), .DEPTH()) u_unknown ();
  leaf u_default ();
  for (genvar i = 0; i < 2; i++) begin : g_loop
    leaf #(.WIDTH(i + 1)) u_loop ();
  end
  for (genvar j = 0; j < UNKNOWN; j++) begin : g_open
    leaf #(.WIDTH(j + 1)) u_open ();
  end
  if (W == 0) begin : g_off
    leaf u_off ();
  end
endmodule
""",
}


def _write(tmp_path, files) -> None:
    for name, text in files.items():
        (tmp_path / name).write_text(text)


@fixture
def sv(tmp_path):
    """Project With SystemVerilog Files."""
    _write(tmp_path, SV)
    return Project.from_dir(tmp_path)


def _values(values: dict[str, Value]) -> dict:
    return {name: value.value if value.value is not None else f"? {value.unknown}" for name, value in values.items()}


def _child(node: HierarchyNode, name: str) -> HierarchyNode:
    return next(child for child in node.children if child.name == name)


def test_sv_params(sv):
    """Parameters With Defaults, Local Parameters, Packages, Enumerations."""
    node = sv.elaborate("leaf")
    assert _values(node.params) == {
        "WIDTH": 8,
        "DEPTH": 256,
        "T": "logic [3:0]",
        # '1 fills the 8 bits of the parameter
        "MASK": 255,
        "NO_DEFAULT": "? no value",
        "PTR_W": 8,
        "TOTAL": 8 + 16 + 32,
        "FN": "? function 'f' is not evaluated",
        "LOOP_A": "? 'LOOP_B' is not known: it depends on itself",
        "LOOP_B": "? 'LOOP_A' is not known: it depends on itself",
        "STATE": 2 + 3,
        "BITS": (16 + 32 + 1 + 2) + 8 + 4,
    }
    assert node.params["DEPTH"] == Value(expr="2 ** WIDTH", value=256)
    assert (node.name, node.module, node.inst, node.definition) == ("leaf", "leaf", "", "leaf.sv:leaf")


def test_sv_ports(sv):
    """Number Of Bits Of Ports."""
    node = sv.elaborate("leaf")
    assert _values(node.ports) == {
        "clk_i": 1,
        "data_i": 8,
        "typed_i": 4,
        "addr_o": 8,
        "req_o": 51,
        "bus": "? 'bus_if.master' is an interface",
    }
    assert node.ports["data_i"] == Value(expr="logic [WIDTH-1:0]", value=8)


def test_sv_instances(sv):
    """The Values Given By Instances Are Applied."""
    top = sv.elaborate("top")
    assert _values(top.params) == {"W": 16}
    assert _values(top.ports) == {"a": 16}
    named = _child(top, "u_named")
    assert (named.inst, named.definition) == ("top.sv:top.u_named", "leaf.sv:leaf")
    assert named.params["WIDTH"] == Value(expr="W", value=16)
    assert named.params["DEPTH"].value == 65536
    # the type is given by the instance and evaluated there
    assert named.params["T"] == Value(expr="half_t", value="half_t")
    assert _values(named.ports) == {
        "clk_i": 1,
        "data_i": 16,
        "typed_i": 8,
        "addr_o": 16,
        "req_o": 51,
        "bus": "? 'bus_if.master' is an interface",
    }
    ordered = _child(top, "u_ordered")
    assert (ordered.params["WIDTH"].value, ordered.params["DEPTH"].value, ordered.params["PTR_W"].value) == (4, 8, 3)
    assert ordered.ports["addr_o"].value == 3
    # a value which is not known is not replaced by the default
    unknown = _child(top, "u_unknown")
    assert unknown.params["WIDTH"] == Value(expr="UNKNOWN", unknown="'UNKNOWN' is not known")
    assert unknown.params["DEPTH"].unknown == "'WIDTH' is not known: 'UNKNOWN' is not known"
    assert unknown.ports["data_i"].unknown == "'WIDTH' is not known: 'UNKNOWN' is not known"
    assert unknown.ports["clk_i"].value == 1
    assert _child(top, "u_default").params["WIDTH"].value == 8
    # the loop is unrolled: the value depends on the iteration
    for index in (0, 1):
        loop = _child(top, f"g_loop[{index}].u_loop")
        assert (loop.inst, loop.multiple) == ("top.sv:top.g_loop.u_loop", False)
        assert loop.params["WIDTH"].value == index + 1
    # the indices of the loop are not known
    loop = _child(top, "g_open.u_open")
    assert loop.multiple
    assert loop.params["WIDTH"].unknown == "'j' is not known"


def test_sv_unit_imports(tmp_path):
    """Imports At File Scope Apply To The Modules And Packages Declared After Them."""
    _write(
        tmp_path,
        {
            "pkg.sv": "package cfg_pkg;\n  localparam int W = 12;\nendpackage\n",
            "mod.sv": """\
import cfg_pkg::*;
package derived_pkg;
  localparam int W2 = W * 2;
endpackage
module mod (input logic [W-1:0] a, input logic [derived_pkg::W2-1:0] b);
endmodule
""",
        },
    )
    project = Project.from_dir(tmp_path)
    node = project.elaborate("mod")
    assert _values(node.ports) == {"a": 12, "b": 24}


def test_sv_top_params(sv):
    """Values Of The Parameters Of The Top."""
    top = sv.elaborate("top", params={"W": 64})
    assert top.params["W"] == Value(expr="64", value=64)
    assert top.ports["a"].value == 64
    assert _child(top, "u_named").ports["typed_i"].value == 32
    leaf = sv.elaborate("leaf", params={"WIDTH": 3, "T": "my_pkg::req_t", "NO_DEFAULT": 1.5})
    assert (leaf.params["DEPTH"].value, leaf.params["NO_DEFAULT"].value) == (8, 1.5)
    assert leaf.ports["typed_i"].value == 51


def test_depth(sv):
    """Depth Limit, Undefined Modules And Missing Tops."""
    top = sv.elaborate("top", depth=0)
    assert (top.children, top.truncated) == ((), True)
    assert sv.elaborate("leaf", depth=0).truncated is False
    assert sv.elaborate("none") is None
    assert [child.name for child in sv.elaborate("top", depth=1).children] == [
        "u_named",
        "u_ordered",
        "u_unknown",
        "u_default",
        "g_loop[0].u_loop",
        "g_loop[1].u_loop",
        "g_open.u_open",
    ]
    # without values: one node per instance, labeled
    names = [child.name for child in sv.hierarchy("top").children]
    assert names[-3:] == ["g_loop.u_loop", "g_open.u_open", "g_off.u_off"]


def test_evaluate(sv):
    """Expressions Within A Module Or Package."""
    assert sv.evaluate("AW + 1", "my_pkg") == Value(expr="AW + 1", value=17)
    assert sv.evaluate("$bits(req_t)", "my_pkg").value == 51
    assert sv.evaluate("$bits(u_t)", "my_pkg").value == 16
    assert sv.evaluate("$bits(plain_e)", "my_pkg").value == 32
    assert sv.evaluate("$bits(req_array_t)", "my_pkg").value == 4 * 51
    assert sv.evaluate("$bits(base_pkg::state_e)", "my_pkg").value == 2
    assert sv.evaluate("A + B0 + B1 + C", "my_pkg").value == 0 + 1 + 2 + 12
    assert sv.evaluate("BASE", "my_pkg").value == 4
    assert sv.evaluate("WIDTH * 2", "leaf").value == 16
    assert sv.evaluate("WIDTH * 2", "leaf", {"WIDTH": 5}).value == 10
    assert sv.evaluate("$bits(ptr_q)", "leaf.sv:leaf").value == 9
    assert sv.evaluate("other_pkg::X", "leaf").unknown == "package 'other_pkg' is not defined in the project"
    assert sv.evaluate("my_pkg::NONE", "leaf").unknown == "'my_pkg::NONE' is not known"
    assert sv.evaluate("$bits(none_t)", "leaf").unknown == "the number of bits of 'none_t' is not known"
    assert sv.evaluate("$bits(other_pkg::t)", "leaf").unknown == "package 'other_pkg' is not defined in the project"
    assert sv.evaluate("$bits(struct packed {logic a;})", "leaf").unknown.startswith("the number of bits of 'struct")
    assert sv.evaluate("1", "none") == Value(expr="1", unknown="'none' is not defined in the project")


def test_json(sv):
    """The Tree Is Data: It Can Be Dumped And Loaded."""
    top = sv.elaborate("top")
    assert HierarchyNode.model_validate_json(top.model_dump_json()) == top
    assert '"params"' in top.overview
    # the plain hierarchy has neither parameters nor ports
    assert sv.hierarchy("top").params == {}
    assert '"params"' not in sv.hierarchy("top").overview


VHDL = {
    "pkg.vhd": """\
package my_pkg is
  constant AW : natural := 16;
  constant DW : natural := 2 ** 5;
  type tech_t is (GENERIC_TECH, XILINX);
  subtype addr_t is std_logic_vector(AW - 1 downto 0);
  type req_t is record
    addr : addr_t;
    data : std_logic_vector(DW - 1 downto 0);
    we   : std_logic;
  end record;
  type mem_t is array (0 to 3) of addr_t;
end package;
""",
    "leaf.vhd": """\
library ieee;
use ieee.std_logic_1164.all;
use work.my_pkg.all;

entity leaf is
  generic (
    WIDTH : natural := 8;
    TECH  : tech_t := GENERIC_TECH;
    FAST  : boolean := WIDTH > 4
  );
  port (
    clk  : in  std_logic;
    data : in  std_logic_vector(WIDTH - 1 downto 0);
    addr : out addr_t;
    req  : out req_t;
    mem  : out mem_t;
    cnt  : out integer;
    vec  : out std_logic_vector
  );
end entity;

architecture rtl of leaf is
  constant TOTAL : natural := WIDTH + AW + work.my_pkg.DW;
  constant IS_XILINX : boolean := TECH = XILINX;
  constant LOG : natural := integer(ceil(log2(real(WIDTH))));
  constant FN : natural := clog2(WIDTH);
begin
end architecture;
""",
    "top.vhd": """\
use work.my_pkg.all;
entity top is
  generic (W : natural := 12);
end entity;
architecture rtl of top is
begin
  u_named : entity work.leaf generic map (WIDTH => W * 2, TECH => XILINX);
  u_ordered : entity work.leaf generic map (4);
  u_default : entity work.leaf;
end architecture;
""",
    "sv_top.sv": "module sv_top;\n  LEAF #(.width(3)) u_vhdl ();\nendmodule\n",
}


@fixture
def vhdl(tmp_path):
    """Project With VHDL Files."""
    _write(tmp_path, VHDL)
    return Project.from_dir(tmp_path)


def test_vhdl_params(vhdl):
    """Generics And Constants. Names Are Not Case Sensitive."""
    node = vhdl.elaborate("leaf")
    assert _values(node.params) == {
        "WIDTH": 8,
        "TECH": "generic_tech",
        "FAST": True,
        "TOTAL": 8 + 16 + 32,
        "IS_XILINX": False,
        "LOG": 3,
        "FN": "? function 'clog2' is not evaluated",
    }


def test_vhdl_ports(vhdl):
    """Number Of Bits Of Ports."""
    node = vhdl.elaborate("leaf")
    assert _values(node.ports) == {
        "clk": 1,
        "data": 8,
        "addr": 16,
        "req": 16 + 32 + 1,
        "mem": 4 * 16,
        "cnt": "? the number of bits of 'integer' is not known",
        "vec": "? 'std_logic_vector' has no range",
    }
    assert node.ports["data"] == Value(expr="std_logic_vector [WIDTH - 1:0]", value=8)


def test_vhdl_instances(vhdl):
    """Generic Maps, By Name And By Order."""
    top = vhdl.elaborate("TOP")
    assert _values(top.params) == {"W": 12}
    named = _child(top, "u_named")
    assert named.params["WIDTH"] == Value(expr="W * 2", value=24)
    assert (named.params["TECH"].value, named.params["IS_XILINX"].value) == ("xilinx", True)
    assert named.ports["data"].value == 24
    ordered = _child(top, "u_ordered")
    assert (ordered.params["WIDTH"].value, ordered.params["FAST"].value) == (4, False)
    assert _child(top, "u_default").params["WIDTH"].value == 8
    assert vhdl.evaluate("AW * 2", "my_pkg").value == 32
    assert vhdl.evaluate("aw + dw", "LEAF").value == 48


def test_mixed_language(vhdl):
    """A SystemVerilog Instance Of A VHDL Entity."""
    node = _child(vhdl.elaborate("sv_top"), "u_vhdl")
    assert node.definition == "leaf.vhd:leaf"
    assert (node.params["WIDTH"].value, node.ports["data"].value) == (3, 3)


# ---------------------------------------------------------------------------------------------------------------------
# real code
# ---------------------------------------------------------------------------------------------------------------------


def _matched(node: HierarchyNode, plain: HierarchyNode):
    """The elaborated nodes, each checked against its node of the plain hierarchy."""
    yield node
    by_inst = {child.inst: child for child in plain.children}
    for child in node.children:
        plain_child = by_inst[child.inst]
        assert (base_key(child.name), child.definition) == (plain_child.name, plain_child.definition)
        yield from _matched(child, plain_child)


def _nodes(node: HierarchyNode):
    yield node
    for child in node.children:
        yield from _nodes(child)


def test_ibex():
    """A Real Core: Values Across Modules And Its Package."""
    project = Project.from_dir(CORPUS / "sv" / "ibex")
    top = project.elaborate("ibex_top")
    core = _child(top, "u_ibex_core")
    assert core.definition == "ibex_core.sv:ibex_core"
    assert (core.params["PMPNumRegions"].value, core.params["MHPMCounterWidth"].value) == (4, 40)
    # an enumeration member of the package, handed down by the instance
    assert core.params["RV32M"].expr == "RV32M"
    assert core.params["RV32M"].value == project.evaluate("RV32MFast", "ibex_pkg").value == 2
    ports = core.ports
    assert [ports[name].value for name in ("clk_i", "hart_id_i", "boot_addr_i", "instr_rdata_i")] == [1, 32, 32, 32]
    cs_registers = _child(core, "cs_registers_i")
    assert cs_registers.params["PMPNumRegions"].value == 4
    counter = _child(cs_registers, "mcycle_counter_i")
    assert counter.params["CounterWidth"] == Value(expr="64", value=64)
    assert counter.ports["counter_val_o"].value == 64
    # types of the package
    assert project.evaluate("$bits(alu_op_e)", "ibex_pkg").value == 7
    assert project.evaluate("$bits(pmp_cfg_t)", "ibex_pkg").value == 6
    # most is known. What is not, tells why
    values = [value for node in _nodes(top) for value in (*node.params.values(), *node.ports.values())]
    known = [value for value in values if value.value is not None]
    assert len(known) / len(values) > 0.9
    assert all(value.unknown for value in values if value.value is None)
    reasons = {value.unknown for value in values if value.value is None}
    assert "the number of bits of 'cap_t' is not known" in reasons


def test_potato():
    """A Real VHDL Project: Constants And Types Of Its Packages."""
    project = Project.from_dir(CORPUS / "vhdl" / "potato")
    core = project.elaborate("pp_core")
    assert core.ports["clk"].value == 1
    assert core.ports["imem_address"].value == 32
    assert core.ports["imem_data_in"].value == 32
    execute = _child(core, "execute")
    assert execute.definition == "pp_execute.vhd:pp_execute"
    assert execute.ports["rs1_addr_in"].value == 5
    assert project.evaluate("CSR_MSTATUS", "pp_csr").value == 0x300


_LITERAL_PORT = re.compile(r"(?:logic|wire|reg|bit)? ?\[(\d+):(\d+)\]")


@mark.parametrize("path", PROJECT_DIRS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_corpus(path):
    """Real Projects: Everything Has A Value Or A Reason. Ports With Literal Dimensions Have Their Size."""
    logging.disable(logging.WARNING)
    try:
        project = Project.from_dir(path)
    finally:
        logging.disable(logging.NOTSET)
    values = 0
    for top in project.tops():
        tree = project.elaborate(top.id)
        plain = project.hierarchy(top.id)
        for node in _matched(tree, plain):
            for value in (*node.params.values(), *node.ports.values()):
                values += 1
                assert (value.value is None) == bool(value.unknown), value
            for value in node.ports.values():
                mat = _LITERAL_PORT.fullmatch(value.expr)
                if mat:
                    assert value.value == abs(int(mat.group(1)) - int(mat.group(2))) + 1, value
            if node.definition:
                module = project.find(node.definition)
                assert list(node.ports) == list(dict.fromkeys(port.name for port in module.ports))
    assert values


def test_sv_corner_cases(tmp_path):
    """Enumerations With Unknown Values, Sized Parameters, Types Which Are Not Known."""
    text = """\
package p;
  typedef enum {A = UNKNOWN, B, C = 5, D, E[UNKNOWN], F} e_t;
  typedef enum {G = 1.5, H} real_e;
  typedef struct packed {} empty_t;
  localparam SIZED = 12'hABC;
  localparam int PLAIN = 3;
  localparam logic [3:0] ARRAY [2] = '{default: '0};
endpackage
module m #(parameter type T) (bus_if.master bus, input T t);
endmodule
"""
    _write(tmp_path, {"p.sv": text})
    project = Project.from_dir(tmp_path)
    assert project.evaluate("A", "p").unknown == "'A' is not known: 'UNKNOWN' is not known"
    assert project.evaluate("B", "p").unknown == "'B' is not known: the value of the member in front is not known"
    assert project.evaluate("C + D", "p").value == 11
    assert project.evaluate("F", "p").unknown == "'F' is not known: the value of the member in front is not known"
    assert project.evaluate("G", "p").unknown == "'G' is not known: value is no integer"
    assert project.evaluate("$bits(empty_t)", "p").unknown == "type 'empty_t' has no fields"
    # the number of bits of a parameter: stated by its value, or its type
    assert project.evaluate("$bits(SIZED)", "p").value == 12
    assert project.evaluate("$bits(PLAIN)", "p").value == 32
    assert project.evaluate("$bits(ARRAY)", "p").value == 8
    assert (
        project.evaluate("$bits(bus.req)", "m").unknown == "the number of bits of the interface 'bus.req' is not known"
    )
    assert project.evaluate("$bits(T)", "m").unknown == "type 'T' is not known"
    assert project.evaluate("$bits(logic signed [7:0])", "m").value == 8
    assert project.evaluate("$bits(a b c)", "m").unknown == "the number of bits of 'a b c' is not known"


def test_vhdl_corner_cases(tmp_path):
    """Ranges And Types Which Are Not Known."""
    text = """\
package p is
  type e_t is (A, B);
  type unconstrained_t is array (natural range <>) of std_logic;
  type matrix_t is array (0 to 1, 0 to 1) of std_logic;
  subtype weird_t is std_logic_vector(3 downto 0)(1 downto 0);
  subtype range_t is natural range 0 to 7;
end package;
entity m is
  port (e : in e_t; u : in unconstrained_t; x : in matrix_t; n : in none_t; w : in weird_t; r : in range_t);
end entity;
"""
    _write(tmp_path, {"p.vhd": text.replace("entity m is", "use work.p.all;\nentity m is")})
    node = Project.from_dir(tmp_path).elaborate("m")
    assert _values(node.ports) == {
        "e": "? enumeration 'e_t' has no number of bits",
        "u": "? the range 'natural range <>' is not known",
        "x": "? the range '0 to 1, 0 to 1' is not known",
        "n": "? the number of bits of 'none_t' is not known",
        "w": "? the range '3 downto 0)(1 downto 0' is not known",
        "r": "? the number of bits of 'natural range 0 to 7' is not known",
    }
